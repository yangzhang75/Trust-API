# Labeled Dataset

`data/labeled_wallets.json` is the ground-truth set used to evaluate the
scoring engine. Every entry cites a **public `label_source`**; nothing is
self-labeled, synthetic, or guessed.

## Composition

| Class | Count | Source(s) |
| --- | --- | --- |
| `sybil` | 30 | **6 distinct Hop airdrop Sybil-report clusters** (issues #3, #192, #197, #211, #336, #345), **5 contiguous members each**. Contiguous = adjacent in the report's connected transfer chain, so intra-cluster on-chain edges survive (validated: a contiguous block is ~40/40 mutually linked, vs 0 for a scattered sample). |
| `human` | 30 | 2 doxxed public identities (vitalik.eth, "Vb") + 28 addresses from Hop's public [eligible list](https://raw.githubusercontent.com/hop-protocol/hop-airdrop/master/src/data/eligibleAddresses.txt) that passed the project's Sybil filter |
| **total** | **60** | |

Each entry carries: `address`, `chains`, `label`, `cluster_id`,
`label_basis`, `label_source` (URL), and a `note`. Sybil `cluster_id` is
the source report (e.g. `hop-3`); each human is a singleton cluster
(`solo-<address>`).

## Why cluster_id + contiguous sampling

Sybil ground truth is about **relationships between wallets** (a connected
transfer chain), not per-wallet traits. An earlier scattered/sorted sample
severed those edges (0 mutual links). Sampling **contiguous cluster
members** keeps the edges, and the **train/test split is cluster-aware**
(a whole cluster lands on one side) so cluster structure never leaks
across the split. See [`scoring-eval.md`](scoring-eval.md).

## What the labels mean (and don't)

- **`sybil` (`community_sybil_report`)** — flagged in a public Sybil report.
  This attributes the reporters' determination; it is strong but not
  infallible ground truth.
- **`human` / `public_identity`** — a doxxed, widely-documented individual
  (only the 2 Vitalik addresses). These are genuine.
- **`human` / `project_vetted_eligible`** — passed Hop's public Sybil
  filter. This is a **proxy for "legitimate participant," not proof of
  humanness.** It can include sophisticated undetected Sybils and some
  contracts/multisigs. Obvious vanity-contract addresses (`0x0000…`) were
  excluded, and no address appears in both classes.

## Known biases (important)

1. **Source concentration.** All 60 wallets come from the **Hop airdrop
   ecosystem** (an L1↔L2 bridge). This is *not* multi-project. Diversifying
   Sybil sources (Optimism, LayerZero, etc.) was attempted but blocked by
   rate limits / non-extractable list formats; it remains future work. The
   evaluation therefore partly measures "can our rules approximate Hop's own
   Sybil review," not general Sybil detection.
2. **L2 skew.** The farming happened largely on **Arbitrum**. Features must
   aggregate Ethereum + Arbitrum to be meaningful (this is why L2 ingestion
   was added — see [`features.md`](features.md)).
3. **Weak positive class.** 28 of 30 "human" labels are the vetted-eligible
   proxy, not verified humans. Human-class metrics should be read with that
   caveat.
4. **No borderline category.** No citable borderline set was available, so
   none is included.

## Train / test split

The set is split deterministically and stratified into ~70% train / ~30%
test (see [`scoring-eval.md`](scoring-eval.md) for the methodology). The
split is committed as data so it never silently changes.

## Regenerating

The dataset was assembled from the cited public sources with `curl` + exact
`grep` extraction (no summarization), so each address is drawn verbatim from
its `label_source`.
