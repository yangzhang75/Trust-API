"""Internal monitoring dashboard (Week 8).

This package holds the *tested* data-loading and auth layer that the
Streamlit app (repo-root ``dashboard/streamlit_app.py``) renders. The
Streamlit UI is a separate process and is deliberately kept out of this
package so nothing here imports streamlit — the data layer stays unit-
testable and covered.
"""
