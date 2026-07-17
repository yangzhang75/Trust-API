"""Trust API — internal monitoring dashboard (Streamlit).

Runs as a separate process (see docker-compose `dashboard` service) reading
the same Postgres + Redis as the API. This module is the UI only; all data
access lives in the tested `trust_api.dashboard.data` layer.

Panels are added across commits 3-5; this scaffold provides page config and
the API-key gate.
"""

from __future__ import annotations

import streamlit as st

from trust_api.config import get_settings
from trust_api.dashboard.auth import verify_dashboard_key

st.set_page_config(page_title="Trust API — Internal Dashboard", layout="wide")


def _require_key() -> None:
    """Block the app behind the API-key gate (see docs/dashboard.md for limits)."""
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


def main() -> None:
    _require_key()
    st.title("Trust API — Internal Dashboard")
    st.caption("Internal monitoring tool. Panels load below.")
    # Panels are wired in commits 3-5.


main()
