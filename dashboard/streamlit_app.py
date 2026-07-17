"""Trust API — internal monitoring dashboard (Streamlit).

Runs as a separate process (see docker-compose `dashboard` service) reading
the same Postgres + Redis as the API. This module is the UI only; all data
access lives in the tested `trust_api.dashboard.data` layer.
"""

from __future__ import annotations

from contextlib import contextmanager

import pandas as pd
import streamlit as st

from trust_api.config import get_settings
from trust_api.dashboard import data
from trust_api.dashboard.auth import verify_dashboard_key
from trust_api.db.session import get_sessionmaker

st.set_page_config(page_title="Trust API — Internal Dashboard", layout="wide")


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
    c[0].metric("Wallets scored (all-time)", ov["wallets_scored_all_time"])
    c[0].metric("Wallets scored (24h)", ov["wallets_scored_24h"])
    c[1].metric("/verify calls (all-time)", ov["verify_calls_all_time"])
    c[1].metric("/verify calls (24h)", ov["verify_calls_24h"])
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
            "⚠️ /verify call counts and success ratio read from `usage_events`, "
            "which the API does not populate yet — showing 0. See docs/dashboard.md."
        )


def distribution_panel(session, since) -> None:
    st.header("Score distribution")
    st.caption("Latest score per wallet in the selected time range.")
    left, mid, right = st.columns(3)
    with left:
        st.subheader("Trust tier")
        st.bar_chart(pd.Series(data.tier_distribution(session, since=since), name="wallets"))
    with mid:
        st.subheader("Human likelihood")
        st.bar_chart(pd.Series(data.likelihood_distribution(session, since=since), name="wallets"))
    with right:
        st.subheader("Confidence")
        st.bar_chart(pd.Series(data.confidence_histogram(session, since=since), name="wallets"))


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
            st.bar_chart(pd.Series(freq, name="wallets"))
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
            "No `usage_events` recorded. The API authenticates against the "
            "configured key list and does not write usage rows yet, so this "
            "panel is empty by design (not an outage). See docs/dashboard.md."
        )
        return
    day = data.since_from_hours(24)
    week = data.since_from_hours(24 * 7)
    left, right = st.columns(2)
    with left:
        st.subheader("Calls per API key (24h)")
        st.dataframe(
            pd.DataFrame(data.usage_by_api_key(session, since=day)), use_container_width=True
        )
    with right:
        st.subheader("Calls per API key (7d)")
        st.dataframe(
            pd.DataFrame(data.usage_by_api_key(session, since=week)), use_container_width=True
        )
    c = st.columns(2)
    c[0].metric("Rate-limit hits (24h)", data.rate_limit_hits(session, since=day))
    with c[1]:
        st.subheader("Failed requests by status (24h)")
        errors = data.errors_by_status(session, since=day)
        st.dataframe(pd.Series(errors, name="count")) if errors else st.caption("None.")


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
