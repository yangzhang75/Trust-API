"""Tests for the scoring evaluation harness."""

from __future__ import annotations

import httpx
import respx
from sqlalchemy.orm import Session

from trust_api.config import Settings
from trust_api.db.models import Wallet, WalletFeature
from trust_api.jobs import evaluate_scoring as ev
from trust_api.schemas.verify import HumanLikelihood

PROVIDER_BASE = "https://api.etherscan.io/v2/api"


def _row(true: str, pred: str) -> ev.EvalRow:
    return ev.EvalRow(
        address="0x" + "a" * 40,
        true_label=true,
        predicted_label=pred,
        human_likelihood="high" if pred == "human" else "low",
        trust_tier="gold" if pred == "human" else "bronze",
        confidence=0.9 if pred == "human" else 0.1,
        risk_flags=[] if pred == "human" else ["low_activity"],
    )


# --- pure metric functions ------------------------------------------------


def test_predict_label() -> None:
    assert ev.predict_label(HumanLikelihood.low) == "sybil"
    assert ev.predict_label(HumanLikelihood.medium) == "human"
    assert ev.predict_label(HumanLikelihood.high) == "human"


def test_accuracy_and_confusion() -> None:
    rows = [_row("human", "human"), _row("sybil", "sybil"), _row("sybil", "human")]
    assert ev.accuracy(rows) == round(2 / 3, 4)
    assert ev.accuracy([]) == 0.0
    m = ev.confusion(rows)
    assert m["human"]["human"] == 1
    assert m["sybil"]["sybil"] == 1
    assert m["sybil"]["human"] == 1


def test_precision_recall() -> None:
    rows = [_row("sybil", "sybil"), _row("sybil", "human"), _row("human", "human")]
    p, r = ev.precision_recall(rows, "sybil")
    assert p == 1.0  # 1 predicted sybil, all correct
    assert r == 0.5  # 2 true sybils, 1 caught
    # empty-denominator path
    assert ev.precision_recall([], "sybil") == (0.0, 0.0)


def test_render_markdown_contains_key_sections() -> None:
    md = ev.render_markdown([_row("human", "human"), _row("sybil", "sybil")], note="test run")
    assert "# Scoring Evaluation" in md
    assert "Confusion matrix" in md
    assert "Per-class metrics" in md
    assert "Per-wallet predictions" in md
    assert "100.00%" in md
    assert "limitations" in md.lower()


# --- evaluate against seeded features (no network) ------------------------


def _seed_features(session: Session, address: str, **cols) -> None:
    w = Wallet(address=address)
    session.add(w)
    session.flush()
    session.add(WalletFeature(wallet_id=w.id, chain="ethereum", payload={}, **cols))
    session.commit()


def test_evaluate_scores_seeded_wallets(db_session: Session) -> None:
    human = "0x" + "1" * 40
    sybil = "0x" + "2" * 40
    _seed_features(
        db_session,
        human,
        wallet_age_days=800,
        tx_count=500,
        active_days=120,
        tx_per_active_day=4.0,
        counterparty_count=300,
        counterparty_diversity_ratio=0.6,
        inbound_ratio=0.5,
        burst_score=3,
        dormancy_flag=False,
        recency_days=1,
    )
    _seed_features(
        db_session,
        sybil,
        wallet_age_days=2,
        tx_count=1,
        active_days=1,
        tx_per_active_day=1.0,
        counterparty_count=1,
        counterparty_diversity_ratio=0.0,
        inbound_ratio=1.0,
        burst_score=0,
        dormancy_flag=False,
        recency_days=0,
    )
    entries = [
        {"address": human, "label": "human"},
        {"address": sybil, "label": "sybil"},
    ]
    rows = ev.evaluate(db_session, entries)
    assert ev.accuracy(rows) == 1.0


def test_evaluate_uses_empty_features_when_missing(db_session: Session) -> None:
    entries = [{"address": "0x" + "9" * 40, "label": "sybil"}]
    rows = ev.evaluate(db_session, entries)
    assert rows[0].predicted_label == "sybil"  # no data -> low -> sybil


# --- prepare_wallet branches ----------------------------------------------


def test_prepare_wallet_skips_when_features_exist(db_session: Session) -> None:
    addr = "0x" + "3" * 40
    _seed_features(
        db_session,
        addr,
        wallet_age_days=1,
        tx_count=1,
        active_days=1,
        tx_per_active_day=1.0,
        counterparty_count=1,
        counterparty_diversity_ratio=0.0,
        inbound_ratio=0.0,
        burst_score=0,
        dormancy_flag=False,
        recency_days=0,
    )
    # Provider set, but features already present -> no ingestion attempted.
    ev.prepare_wallet(db_session, addr, Settings(etherscan_api_key="k"))


def test_prepare_wallet_skips_without_provider(db_session: Session) -> None:
    ev.prepare_wallet(db_session, "0x" + "4" * 40, Settings(etherscan_api_key=""))
    assert ev._features_row(db_session, "0x" + "4" * 40) is None


@respx.mock
def test_prepare_wallet_ingests_when_provider_set(db_session: Session) -> None:
    addr = "0x52908400098527886E0F7030069857D2E4169EE7"
    raw = {
        "hash": "0x" + "e" * 64,
        "from": addr.lower(),
        "to": "0x000000000000000000000000000000000000dead",
        "value": "1",
        "timeStamp": "1700000000",
        "blockNumber": "18000000",
        "contractAddress": "",
    }
    respx.get(PROVIDER_BASE).mock(
        return_value=httpx.Response(200, json={"status": "1", "message": "OK", "result": [raw]})
    )
    settings = Settings(
        etherscan_api_key="k",
        etherscan_base_url=PROVIDER_BASE,
        ingestion_backoff_seconds=0,
        ingestion_cache_ttl_seconds=0,
    )
    ev.prepare_wallet(db_session, addr, settings)
    assert ev._features_row(db_session, addr) is not None


@respx.mock
def test_prepare_wallet_handles_ingestion_error(db_session: Session) -> None:
    addr = "0x52908400098527886E0F7030069857D2E4169EE7"
    respx.get(PROVIDER_BASE).mock(
        return_value=httpx.Response(
            200, json={"status": "0", "message": "Invalid API Key", "result": "bad"}
        )
    )
    settings = Settings(
        etherscan_api_key="k",
        etherscan_base_url=PROVIDER_BASE,
        ingestion_backoff_seconds=0,
        ingestion_cache_ttl_seconds=0,
    )
    ev.prepare_wallet(db_session, addr, settings)  # error caught, no crash
    assert ev._features_row(db_session, addr) is None


def test_load_dataset_reads_committed_file() -> None:
    wallets = ev.load_dataset()
    assert len(wallets) >= 60
    assert {w["label"] for w in wallets} == {"human", "sybil"}
