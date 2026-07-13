"""SQLAlchemy 2.0 ORM models for the Trust API.

Schema only — Week 1 creates these tables but most stay unused until
Week 2 wires the pipeline to persistence. Two invariants enforced here:
  * proofs/wallet_features payloads are jsonb, never raw transaction data;
  * api_keys store a key_hash, never plaintext.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
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
    # Ingestion aggregates (Week 2): populated by the ETL load step.
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tx_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)

    features: Mapped[list[WalletFeature]] = relationship(back_populates="wallet")
    scores: Mapped[list[TrustScore]] = relationship(back_populates="wallet")
    proofs: Mapped[list[Proof]] = relationship(back_populates="wallet")
    transactions: Mapped[list[WalletTransaction]] = relationship(back_populates="wallet")


class WalletFeature(Base):
    """Derived, privacy-preserving behavioral features for a wallet.

    One row per (wallet, chain). Aggregated only — never raw transaction
    data. The typed columns are the source of truth; ``payload`` keeps a
    jsonb copy for ad-hoc querying.
    """

    __tablename__ = "wallet_features"
    __table_args__ = (
        UniqueConstraint("wallet_id", "chain", name="uq_wallet_features_wallet_chain"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wallet_id: Mapped[int] = mapped_column(
        ForeignKey("wallets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    # Aggregated, privacy-preserving features — never raw transaction data.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # --- Behavioral features (Week 3) ---
    wallet_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tx_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tx_per_active_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    counterparty_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    counterparty_diversity_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    inbound_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    burst_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dormancy_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    recency_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Graph / cluster features (Week 4 reinforcement, "B") ---
    shared_funder_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    counterparty_overlap_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    funding_chain_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cluster_size_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    wallet: Mapped[Wallet] = relationship(back_populates="features")


class WalletTransaction(Base):
    """A normalized on-chain transaction for a wallet (internal storage).

    Raw-ish tx records live here for feature engineering; the public API
    never exposes them. Idempotency is enforced by a unique
    (wallet_id, tx_hash) constraint so re-ingestion creates no duplicates.
    """

    __tablename__ = "wallet_transactions"
    __table_args__ = (UniqueConstraint("wallet_id", "tx_hash", name="uq_wallet_tx_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wallet_id: Mapped[int] = mapped_column(
        ForeignKey("wallets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    block_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value_wei: Mapped[int] = mapped_column(Numeric(80, 0), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  # in | out | self
    counterparty: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    wallet: Mapped[Wallet] = relationship(back_populates="transactions")


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


class TrustScoreHistory(Base):
    """Append-only scoring history (Week 5).

    One row per (wallet, scorer_version): re-running the same scorer version
    updates that row in place; a new scorer_version appends a new row, so
    scores from different scorer versions stay distinguishable.
    """

    __tablename__ = "trust_score_history"
    __table_args__ = (
        UniqueConstraint("wallet_id", "scorer_version", name="uq_score_history_wallet_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wallet_id: Mapped[int] = mapped_column(
        ForeignKey("wallets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    human_likelihood: Mapped[str] = mapped_column(String(16), nullable=False)
    trust_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    risk_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    scorer_version: Mapped[str] = mapped_column(String(32), nullable=False)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


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
    # Week 6: real signing.
    key_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)

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
