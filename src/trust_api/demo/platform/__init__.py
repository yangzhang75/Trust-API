"""Mock platform (Week 10) — a CLIENT of the Trust API, not part of it.

A standalone FastAPI service that consumes the Trust API over its public HTTP
interface (real API key, real requests) to demonstrate three integration
patterns: social login, creator verification, and bot filtering. It never
imports Trust API scoring/proof internals — that is the point: it proves the
API is usable from the outside.
"""
