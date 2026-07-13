"""Tests for the proof revocation job runner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from trust_api.db.models import Proof, Wallet
from trust_api.jobs import revoke as revoke_job

W1 = "0x52908400098527886E0F7030069857D2E4169EE7"


def _proof(session: Session, wallet_id: int, signature: str) -> Proof:
    now = datetime.now(UTC)
    p = Proof(
        wallet_id=wallet_id,
        payload={"signature": signature},
        signature=signature,
        issued_at=now,
        expires_at=now + timedelta(hours=24),
        valid_for_hours=24,
        key_id="k" * 16,
    )
    session.add(p)
    session.flush()
    return p


def _wallet(session: Session, address: str = W1) -> Wallet:
    w = Wallet(address=address)
    session.add(w)
    session.flush()
    return w


def test_revoke_by_id_flips_flag(db_session: Session) -> None:
    w = _wallet(db_session)
    p = _proof(db_session, w.id, "sig-a")
    db_session.commit()

    assert revoke_job.revoke_by_id(db_session, p.id) == 1
    db_session.refresh(p)
    assert p.revoked is True


def test_revoke_by_id_already_revoked_is_noop(db_session: Session) -> None:
    w = _wallet(db_session)
    p = _proof(db_session, w.id, "sig-b")
    db_session.commit()
    revoke_job.revoke_by_id(db_session, p.id)

    # Second revoke of the same proof affects no rows.
    assert revoke_job.revoke_by_id(db_session, p.id) == 0


def test_revoke_by_id_unknown_returns_zero(db_session: Session) -> None:
    assert revoke_job.revoke_by_id(db_session, 999999) == 0


def test_revoke_by_wallet_revokes_all(db_session: Session) -> None:
    w = _wallet(db_session)
    _proof(db_session, w.id, "sig-c")
    _proof(db_session, w.id, "sig-d")
    db_session.commit()

    assert revoke_job.revoke_by_wallet(db_session, W1) == 2
    revoked = [p.revoked for p in db_session.query(Proof).all()]
    assert revoked == [True, True]


def test_revoke_by_wallet_unknown_returns_zero(db_session: Session) -> None:
    assert revoke_job.revoke_by_wallet(db_session, W1) == 0


def test_run_dispatches_proof_id(db_session: Session) -> None:
    w = _wallet(db_session)
    p = _proof(db_session, w.id, "sig-e")
    db_session.commit()
    args = revoke_job._parser().parse_args(["--proof-id", str(p.id)])
    assert revoke_job.run(db_session, args) == 1


def test_run_dispatches_wallet(db_session: Session) -> None:
    w = _wallet(db_session)
    _proof(db_session, w.id, "sig-f")
    db_session.commit()
    args = revoke_job._parser().parse_args(["--wallet", W1])
    assert revoke_job.run(db_session, args) == 1


def test_main_by_proof_id(db_engine: Engine, monkeypatch) -> None:
    factory = sessionmaker(bind=db_engine)
    with factory() as s:
        w = _wallet(s, "0xde709f2102306220921060314715629080e2fb77")
        p = _proof(s, w.id, "sig-g")
        s.commit()
        pid = p.id
    monkeypatch.setattr(revoke_job, "get_sessionmaker", lambda: factory)
    revoke_job.main(["--proof-id", str(pid)])
    with factory() as s:
        assert s.get(Proof, pid).revoked is True


def test_main_by_wallet(db_engine: Engine, monkeypatch) -> None:
    factory = sessionmaker(bind=db_engine)
    addr = "0x000000000000000000000000000000000000cafe"
    with factory() as s:
        w = _wallet(s, addr)
        wid = w.id
        _proof(s, wid, "sig-h")
        s.commit()
    monkeypatch.setattr(revoke_job, "get_sessionmaker", lambda: factory)
    revoke_job.main(["--wallet", addr])
    with factory() as s:
        assert all(p.revoked for p in s.query(Proof).filter_by(wallet_id=wid).all())
