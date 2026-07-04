"""Evaluate the scoring engine against the labeled dataset.

Ingests + computes features for each labeled wallet (when a provider is
configured), scores them, and renders a confusion matrix + per-class
metrics + a per-wallet breakdown to docs/scoring-eval.md.

Usage: python -m trust_api.jobs.evaluate_scoring
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from trust_api.config import Settings, get_settings
from trust_api.core.logging import configure_logging, get_logger
from trust_api.db.models import Wallet, WalletFeature
from trust_api.db.session import get_sessionmaker
from trust_api.schemas.verify import HumanLikelihood
from trust_api.services.features import EMPTY_FEATURES, compute_features
from trust_api.services.ingestion import IngestionError, ingest_wallet
from trust_api.services.scoring import score

logger = get_logger(__name__)

DATASET = Path(__file__).resolve().parent.parent.parent.parent / "data" / "labeled_wallets.json"
LABEL_TO_CLASS = {"human": "human", "sybil": "sybil"}
CLASSES = ("human", "sybil")


@dataclass(frozen=True)
class EvalRow:
    address: str
    true_label: str
    predicted_label: str
    human_likelihood: str
    trust_tier: str
    confidence: float
    risk_flags: list[str]

    @property
    def correct(self) -> bool:
        return self.true_label == self.predicted_label


def load_dataset(path: Path = DATASET) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["wallets"]


def predict_label(likelihood: HumanLikelihood) -> str:
    """low -> sybil; medium/high -> human."""
    return "sybil" if likelihood is HumanLikelihood.low else "human"


def _features_row(session: Session, address: str) -> WalletFeature | None:
    return session.execute(
        select(WalletFeature).join(Wallet).where(Wallet.address == address)
    ).scalar_one_or_none()


def prepare_wallet(session: Session, address: str, settings: Settings, *, now=None) -> None:
    """Ingest + compute features for a wallet if missing and provider is set."""
    if _features_row(session, address) is not None:
        return
    if not settings.ingestion_provider_configured:
        return
    try:
        result = asyncio.run(ingest_wallet(session, address, settings=settings))
        compute_features(session, result.wallet_id, now=now)
    except IngestionError as exc:
        logger.warning("ingest failed for %s: %s", address, exc)
        session.rollback()


def evaluate(session: Session, entries: list[dict]) -> list[EvalRow]:
    """Score each labeled wallet from its stored features (no network)."""
    rows: list[EvalRow] = []
    for entry in entries:
        features = _features_row(session, entry["address"]) or EMPTY_FEATURES
        result = score(features)
        rows.append(
            EvalRow(
                address=entry["address"],
                true_label=LABEL_TO_CLASS[entry["label"]],
                predicted_label=predict_label(result.human_likelihood),
                human_likelihood=result.human_likelihood.value,
                trust_tier=result.trust_tier.value,
                confidence=result.confidence_score,
                risk_flags=[f.value for f in result.risk_flags],
            )
        )
    return rows


def accuracy(rows: list[EvalRow]) -> float:
    return round(sum(r.correct for r in rows) / len(rows), 4) if rows else 0.0


def precision_recall(rows: list[EvalRow], cls: str) -> tuple[float, float]:
    tp = sum(1 for r in rows if r.true_label == cls and r.predicted_label == cls)
    fp = sum(1 for r in rows if r.true_label != cls and r.predicted_label == cls)
    fn = sum(1 for r in rows if r.true_label == cls and r.predicted_label != cls)
    precision = round(tp / (tp + fp), 4) if (tp + fp) else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) else 0.0
    return precision, recall


def confusion(rows: list[EvalRow]) -> dict[str, dict[str, int]]:
    matrix = {t: dict.fromkeys(CLASSES, 0) for t in CLASSES}
    for r in rows:
        matrix[r.true_label][r.predicted_label] += 1
    return matrix


def render_markdown(rows: list[EvalRow], *, note: str) -> str:
    m = confusion(rows)
    lines = [
        "# Scoring Evaluation",
        "",
        note,
        "",
        "Decision rule: `human_likelihood == low` -> predicted **sybil**; "
        "`medium`/`high` -> predicted **human**.",
        "",
        f"**Accuracy:** {accuracy(rows):.2%} over {len(rows)} labeled wallets.",
        "",
        "## Confusion matrix (rows = true, cols = predicted)",
        "",
        "| true \\ pred | human | sybil |",
        "| --- | --- | --- |",
        f"| human | {m['human']['human']} | {m['human']['sybil']} |",
        f"| sybil | {m['sybil']['human']} | {m['sybil']['sybil']} |",
        "",
        "## Per-class metrics",
        "",
        "| class | precision | recall |",
        "| --- | --- | --- |",
    ]
    for cls in CLASSES:
        p, rec = precision_recall(rows, cls)
        lines.append(f"| {cls} | {p:.2%} | {rec:.2%} |")
    lines += [
        "",
        "## Per-wallet predictions",
        "",
        "| address | label | predicted | likelihood | tier | confidence | risk flags |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        flags = ", ".join(r.risk_flags) or "—"
        mark = "✅" if r.correct else "❌"
        lines.append(
            f"| `{r.address[:10]}…` | {r.true_label} | {r.predicted_label} {mark} | "
            f"{r.human_likelihood} | {r.trust_tier} | {r.confidence} | {flags} |"
        )
    lines += [
        "",
        "## Interpretation, limitations & improvement plan",
        "",
        "- **Small, imbalanced labeled set.** Only 2 verified human addresses vs 10 "
        "Sybils — the human-class metrics are high-variance (one miss moves precision "
        "by 50 points). The set is intentionally not padded with unverified addresses.",
        "- **L2-vs-mainnet gap.** The Sybil cluster farmed on Arbitrum (L2); ingestion "
        "currently covers Ethereum mainnet only, so these wallets show thin mainnet "
        "history and score low. Sybil recall here partly reflects 'thin mainnet "
        "footprint' rather than direct on-chain Sybil-pattern detection.",
        "- **Human false negatives are real.** A high-activity human address can trip "
        "`bot_burst` / `low_counterparty_diversity` from a recent bursty window; the "
        "rules do not yet distinguish organic bursts from bot bursts.",
        "- **Rule-based by design (no ML).** Transparent and inspectable; not tuned to "
        "this small dataset. Metrics are reported as-is, not optimized to look good.",
        "- **Improvement plan:** add L2 ingestion (score wallets on the chain they act "
        "on); grow a larger, balanced, verified labeled set (incl. borderline); tune "
        "burst/diversity thresholds against that set; add funding-source / counterparty-"
        "graph clustering for genuine Sybil-ring detection.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:  # pragma: no cover
    settings = get_settings()
    configure_logging(settings.log_level)
    entries = load_dataset()
    with get_sessionmaker()() as session:
        for entry in entries:
            prepare_wallet(session, entry["address"], settings)
        rows = evaluate(session, entries)
    note = (
        "Generated by `python -m trust_api.jobs.evaluate_scoring` against the "
        "verified labeled dataset (data/labeled_wallets.json)."
    )
    out = DATASET.parent.parent / "docs" / "scoring-eval.md"
    out.write_text(render_markdown(rows, note=note), encoding="utf-8")
    logger.info("wrote %s (accuracy %.2f%%)", out, accuracy(rows) * 100)


if __name__ == "__main__":  # pragma: no cover
    main()
