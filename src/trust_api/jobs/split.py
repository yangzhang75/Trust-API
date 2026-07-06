"""Deterministic, cluster-aware train/test split for the labeled dataset.

The split is a pure function of each wallet's ``cluster_id``
(sha256(cluster_id) % 100 < 30 -> test), so it is:
  * deterministic — same input always yields the same split;
  * stable — adding/removing a wallet never reshuffles the others;
  * **cluster-aware** — every wallet in a Sybil cluster lands on the SAME
    side, so a cluster never spans train and test (which would leak the
    cluster's structure). Humans are singleton clusters, so they split
    individually.

The split is committed to data/train_test_split.json as the source of
truth. Tuning may look at the TRAIN split only; the TEST split is scored
once per reported evaluation. See docs/scoring-eval.md.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent.parent.parent / "data"
DATASET = _DATA / "labeled_wallets.json"
SPLIT_FILE = _DATA / "train_test_split.json"

TEST_PERCENT = 30  # sha256(cluster_id) % 100 < TEST_PERCENT -> test split


def _cluster_in_test(cluster_id: str) -> bool:
    bucket = int(hashlib.sha256(cluster_id.encode("utf-8")).hexdigest(), 16) % 100
    return bucket < TEST_PERCENT


def build_split(wallets: list[dict]) -> dict:
    """Build the deterministic cluster-aware split from dataset entries."""
    train, test = [], []
    for w in wallets:
        target = test if _cluster_in_test(w["cluster_id"]) else train
        target.append(w["address"].lower())
    return {
        "method": "deterministic cluster-aware: sha256(cluster_id) % 100 < 30 -> test; "
        "a Sybil cluster never spans train and test",
        "test_percent": TEST_PERCENT,
        "train": sorted(train),
        "test": sorted(test),
    }


def load_dataset(path: Path = DATASET) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["wallets"]


def load_split(path: Path = SPLIT_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def split_sets(path: Path = SPLIT_FILE) -> tuple[set[str], set[str]]:
    """Return (train_addresses, test_addresses) as lowercase sets."""
    data = load_split(path)
    return set(data["train"]), set(data["test"])


def main() -> None:  # pragma: no cover
    split = build_split(load_dataset())
    SPLIT_FILE.write_text(json.dumps(split, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {SPLIT_FILE}: {len(split['train'])} train / {len(split['test'])} test")


if __name__ == "__main__":  # pragma: no cover
    main()
