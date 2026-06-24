"""SQLAlchemy 2.0 ORM models for the Trust API.

Schema only — Week 1 creates these tables but most stay unused until
Week 2 wires the pipeline to persistence. Two invariants enforced here:
  * proofs/wallet_features payloads are jsonb, never raw transaction data;
  * api_keys store a key_hash, never plaintext.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trust_api.db.session import Base


class Wallet(Base):
    """A wallet address we have assessed at least once."""

    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    address: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    features: Mapped[list[WalletFeature]] = relationship(back_populates="wallet")
    scores: Mapped[list[TrustScore]] = relationship(back_populates="wallet")
    proofs: Mapped[list[Proof]] = relationship(back_populates="wallet")


class WalletFeature(Base):
    """Derived features for a wallet on a given chain (jsonb payload)."""

    __tablename__ = "wallet_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wallet_id: Mapped[int] = mapped_column(
        ForeignKey("wallets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    # Aggregated, privacy-preserving features — never raw transaction data.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    wallet: Mapped[Wallet] = relationship(back_populates="features")


class TrustScore(Base):
    """A scored trust assessment for a wallet."""

    __tablename__ = "trust_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wallet_id: Mapped[int] = mapped_column(
        ForeignKey("wallets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    human_likelihood: Mapped[str] = mapped_column(String(16), nullable=False)
    trust_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    risk_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    wallet: Mapped[Wallet] = relationship(back_populates="scores")


class Proof(Base):
    """A time-bounded attestation issued for a wallet (jsonb payload only)."""

    __tablename__ = "proofs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wallet_id: Mapped[int] = mapped_column(
        ForeignKey("wallets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Signed attestation payload — never raw transaction data.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    signature: Mapped[str] = mapped_column(String(256), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_for_hours: Mapped[int] = mapped_column(Integer, nullable=False)

    wallet: Mapped[Wallet] = relationship(back_populates="proofs")


class ApiKey(Base):
    """An API consumer credential. Stores a hash of the key, never plaintext."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UsageEvent(Base):
    """A record of an API call, for metering and abuse analysis."""

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    api_key_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), index=True, nullable=True
    )
    wallet_id: Mapped[int | None] = mapped_column(
        ForeignKey("wallets.id", ondelete="SET NULL"), index=True, nullable=True
    )
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
