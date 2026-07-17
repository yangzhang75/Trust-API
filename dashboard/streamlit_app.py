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


def main() -> None:
    _require_key()
    st.title("Trust API — Internal Dashboard")
    _range_label, hours = _time_range()
    since = data.since_from_hours(hours)
    with _session() as session:
        overview_panel(session)
        st.divider()
        distribution_panel(session, since)


main()
