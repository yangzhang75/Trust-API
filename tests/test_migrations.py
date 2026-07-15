"""Tests that Alembic migrations apply cleanly and stay in sync with the ORM.

These close the gap flagged in docs/test-map.md: previously the schema was
only ever built via ``Base.metadata.create_all`` in tests, so a migration
that drifted from the ORM models would go undetected.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from tests.conftest import _alembic_upgrade_head, _reset_public_schema, _test_db_url
from trust_api.db.session import Base

# Current head revision — bump when a new migration is added.
HEAD_REVISION = "0006_proof_signing_columns"

EXPECTED_TABLES = {
    "wallets",
    "wallet_features",
    "wallet_transactions",
    "trust_scores",
    "trust_score_history",
    "proofs",
    "api_keys",
    "usage_events",
}


def _schema_snapshot(engine: Engine) -> dict[str, dict[str, tuple[str, bool]]]:
    """Reflect {table: {column: (type_str, nullable)}}, excluding alembic_version."""
    insp = inspect(engine)
    snapshot: dict[str, dict[str, tuple[str, bool]]] = {}
    for table in insp.get_table_names():
        if table == "alembic_version":
            continue
        snapshot[table] = {
            col["name"]: (str(col["type"]), bool(col["nullable"]))
            for col in insp.get_columns(table)
        }
    return snapshot


def test_migrations_apply_to_head_cleanly(raw_pg_engine: Engine) -> None:
    _reset_public_schema(raw_pg_engine)
    _alembic_upgrade_head(_test_db_url())

    tables = set(inspect(raw_pg_engine).get_table_names())
    assert EXPECTED_TABLES <= tables
    assert "alembic_version" in tables
    with raw_pg_engine.connect() as conn:
        version = conn.execute(text("select version_num from alembic_version")).scalar_one()
    assert version == HEAD_REVISION


def test_migration_schema_matches_orm_models(raw_pg_engine: Engine) -> None:
    # Build the schema via migrations, snapshot it.
    _reset_public_schema(raw_pg_engine)
    _alembic_upgrade_head(_test_db_url())
    migrated = _schema_snapshot(raw_pg_engine)

    # Build the schema via the ORM metadata, snapshot it.
    _reset_public_schema(raw_pg_engine)
    Base.metadata.create_all(raw_pg_engine)
    orm = _schema_snapshot(raw_pg_engine)

    assert set(migrated) == set(orm), (
        f"table drift — migrations-only={set(migrated) - set(orm)}, "
        f"orm-only={set(orm) - set(migrated)}"
    )
    for table in sorted(orm):
        assert (
            migrated[table] == orm[table]
        ), f"column drift in {table}: migrations={migrated[table]} vs orm={orm[table]}"
