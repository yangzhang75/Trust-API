"""Trust API — internal monitoring dashboard (Streamlit).

Runs as a separate process (see docker-compose `dashboard` service) reading
the same Postgres + Redis as the API. This module is the UI only; all data
access lives in the tested `trust_api.dashboard.data` layer.
"""

from __future__ import annotations

from contextlib import contextmanager

import altair as alt
import pandas as pd
import streamlit as st

from trust_api.config import get_settings
from trust_api.dashboard import data
from trust_api.dashboard.auth import verify_dashboard_key
from trust_api.db.session import get_sessionmaker

st.set_page_config(page_title="Trust API — Internal Dashboard", layout="wide")
# Give the page top padding so the title isn't clipped by the top edge.
st.markdown("<style>.block-container{padding-top:2.5rem;}</style>", unsafe_allow_html=True)


def _bar_chart(counts: dict, x_label: str) -> alt.Chart:
    """A count bar chart with a Y-axis fixed to [0, max] and explicit integer
    ticks (never negative, no fractional/duplicate labels), and horizontal,
    untruncated X labels."""
    order = [str(k) for k in counts]
    values = list(counts.values())
    top = max([*values, 1])  # avoid a degenerate [0, 0] domain
    df = pd.DataFrame({x_label: order, "count": values})
    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(f"{x_label}:N", sort=order, axis=alt.Axis(labelAngle=0, labelLimit=1000)),
            y=alt.Y(
                "count:Q",
                scale=alt.Scale(domain=[0, top]),
                axis=alt.Axis(values=list(range(top + 1)), format="d"),
            ),
        )
        .properties(height=260)
    )


@contextmanager
def _session():
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def _require_key() -> None:
    """API-key gate. App-level only — see docs/dashboard.md for its limits."""
    if st.session_state.get("authed"):
        return
    st.title("Trust API — Internal Dashboard")
    st.caption("Enter a dashboard admin key or a valid API key to continue.")
    key = st.text_input("API key", type="password")
    if st.button("Enter") and key:
        if verify_dashboard_key(get_settings(), key):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Invalid key.")
    st.stop()


def _time_range() -> tuple[str, int | None]:
    """Sidebar time-range picker shared by the time-filtered panels."""
    label = st.sidebar.selectbox("Time range", list(data.TIME_RANGES), index=0)
    return label, data.TIME_RANGES[label]


# --- panels ---------------------------------------------------------------


def overview_panel(session) -> None:
    st.header("Overview")
    ov = data.overview(session)

    c = st.columns(4)
    scored_help = (
        "Distinct wallets with a persisted score (trust_score_history). "
        "Every /verify records one."
    )
    calls_help = (
        "All /verify requests logged in usage_events, including 401/400. Differs from "
        "wallets scored: repeat calls and rejected requests don't add distinct scored wallets."
    )
    c[0].metric("Wallets scored (all-time)", ov["wallets_scored_all_time"], help=scored_help)
    c[0].metric("Wallets scored (24h)", ov["wallets_scored_24h"], help=scored_help)
    c[1].metric("/verify calls (all-time)", ov["verify_calls_all_time"], help=calls_help)
    c[1].metric("/verify calls (24h)", ov["verify_calls_24h"], help=calls_help)
    sf = ov["success_failure_24h"]
    total = sf["success"] + sf["failure"]
    ratio = f"{(sf['success'] / total * 100):.0f}%" if total else "—"
    c[2].metric("Success ratio (24h)", ratio, help=f"{sf['success']} ok / {sf['failure']} failed")
    c[2].metric("Avg scoring time", f"{ov['avg_scoring_seconds']:.3f}s")
    last = ov["last_scoring_at"]
    c[3].metric("Last scoring", last.strftime("%Y-%m-%d %H:%M") if last else "never")
    c[3].metric("Scorer version", ov["scorer_version"])

    if not data.usage_events_present(session):
        st.info(
            "No requests recorded in `usage_events` yet — /verify counts and "
            "success ratio show 0 until the API serves traffic. See docs/dashboard.md."
        )


def distribution_panel(session, since) -> None:
    st.header("Score distribution")
    tiers = data.tier_distribution(session, since=since)
    if sum(tiers.values()) == 0:
        st.info(
            "📭 **No scored wallets yet in this range.** Distributions appear "
            "once wallets are scored — every `/verify` call records a score, and "
            "the worker scores ingested wallets. Widen the time range or send "
            "some `/verify` traffic."
        )
        return
    st.caption("Latest score per wallet in the selected time range.")
    left, mid, right = st.columns(3)
    with left:
        st.subheader("Trust tier")
        st.altair_chart(_bar_chart(tiers, "tier"), use_container_width=True)
    with mid:
        st.subheader("Human likelihood")
        st.altair_chart(
            _bar_chart(data.likelihood_distribution(session, since=since), "likelihood"),
            use_container_width=True,
        )
    with right:
        st.subheader("Confidence")
        st.altair_chart(
            _bar_chart(data.confidence_histogram(session, since=since), "bucket"),
            use_container_width=True,
        )


def _render_wallet_detail(info: dict) -> None:
    """Shared wallet drill-down: identity, features, score history, proofs."""
    c = st.columns(4)
    c[0].metric("Stored transactions", info["stored_tx_count"])
    c[1].metric("Wallet tx_count", info["wallet_tx_count"])
    c[2].metric(
        "First seen", info["first_seen"].strftime("%Y-%m-%d") if info["first_seen"] else "—"
    )
    c[3].metric("Last seen", info["last_seen"].strftime("%Y-%m-%d") if info["last_seen"] else "—")

    st.markdown("**Features**")
    if info["features"]:
        st.dataframe(pd.DataFrame([info["features"]]).T.rename(columns={0: "value"}))
    else:
        st.caption("No features computed for this wallet yet.")

    st.markdown("**Score history** (newest first, all scorer versions)")
    if info["score_history"]:
        st.dataframe(pd.DataFrame(info["score_history"]), use_container_width=True)
    else:
        st.caption("No scores recorded.")

    st.markdown("**Proofs** (metadata only — no raw transaction data)")
    if info["proofs"]:
        st.dataframe(pd.DataFrame(info["proofs"]), use_container_width=True)
    else:
        st.caption("No proofs issued.")


def risk_panel(session, since) -> None:
    st.header("Risk flags")
    freq = data.risk_flag_frequency(session, since=since)
    left, right = st.columns([1, 2])
    with left:
        st.subheader("Most frequent flags")
        if freq:
            st.altair_chart(_bar_chart(freq, "flag"), use_container_width=True)
        else:
            st.caption("No flags in this time range.")
    with right:
        st.subheader("Recent flagged wallets")
        flagged = data.recent_flagged_wallets(session, since=since, limit=25)
        if flagged:
            st.dataframe(pd.DataFrame(flagged), use_container_width=True)
            st.caption(f"Showing the {len(flagged)} most recent flagged wallets (max 25).")
            for w in flagged:
                with st.expander(
                    f"{w['address']} — {w['trust_tier']} — {', '.join(w['risk_flags'])}"
                ):
                    info = data.inspect_wallet(session, w["address"])
                    if info:
                        _render_wallet_detail(info)
        else:
            st.caption("No flagged wallets in this time range.")


def inspector_panel(session) -> None:
    st.header("Wallet inspector")
    st.caption("Paste a wallet address to see why it got its score.")
    address = st.text_input("Wallet address").strip()
    if not address:
        return
    info = data.inspect_wallet(session, address)
    if info is None:
        st.warning("This wallet is not known to the system (never ingested or scored).")
        return
    st.success(f"Found {info['address']}")
    _render_wallet_detail(info)


def usage_panel(session) -> None:
    st.header("API usage")
    if not data.usage_events_present(session):
        st.warning(
            "No requests recorded yet — the API logs a `usage_events` row per "
            "request, so this panel populates once it serves traffic. Per-key "
            "rows are keyed by a hashed API key (api_keys table still empty)."
        )
        return
    day = data.since_from_hours(24)
    st.subheader("Calls per API key — 24h vs 7d")
    st.dataframe(pd.DataFrame(data.usage_by_api_key_windows(session)), use_container_width=True)
    st.caption(
        "Hashed API key (sha256[:16]); NULL = unauthenticated/invalid request. "
        "24h ⊆ 7d, so `calls_24h ≤ calls_7d` for every key."
    )
    c = st.columns(2)
    c[0].metric("Rate-limit hits (24h)", data.rate_limit_hits(session, since=day))
    with c[1]:
        st.subheader("Failed requests by status (24h)")
        errors = data.errors_by_status(session, since=day)
        if errors:
            st.dataframe(pd.Series(errors, name="count"))
        else:
            st.caption("None.")


def health_panel(session, settings) -> None:
    st.header("System health")
    c = st.columns(2)
    c[0].metric("Postgres", "✅ up" if data.db_healthy(session) else "❌ down")
    c[1].metric("Redis", "✅ up" if data.redis_healthy(settings.redis_url) else "❌ down")

    st.subheader("Scoring metrics (shared Redis — same source as GET /metrics)")
    st.dataframe(pd.Series(data.metrics_snapshot(), name="value"), use_container_width=True)
    st.caption(
        "Recent structured error logs are not surfaced here — logs stream to "
        "each container's stdout/stderr (no log store). Deferred; see docs/dashboard.md."
    )


def main() -> None:
    _require_key()
    settings = get_settings()
    st.title("Trust API — Internal Dashboard")
    _range_label, hours = _time_range()
    since = data.since_from_hours(hours)
    with _session() as session:
        overview_panel(session)
        st.divider()
        distribution_panel(session, since)
        st.divider()
        risk_panel(session, since)
        st.divider()
        inspector_panel(session)
        st.divider()
        usage_panel(session)
        st.divider()
        health_panel(session, settings)


main()
