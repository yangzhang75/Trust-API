# Labeled Dataset

`data/labeled_wallets.json` is the ground-truth set used to evaluate the
scoring engine. Every entry cites a **public `label_source`**; nothing is
self-labeled, synthetic, or guessed.

## Composition

| Class | Count | Source(s) |
| --- | --- | --- |
| `sybil` | 30 | Hop airdrop Sybil reports [#3](https://github.com/hop-protocol/hop-airdrop/issues/3) (15) and [#192](https://github.com/hop-protocol/hop-airdrop/issues/192) (15) — two distinct community-reported farming clusters |
| `human` | 30 | 2 doxxed public identities (vitalik.eth, "Vb") + 28 addresses from Hop's public [eligible list](https://raw.githubusercontent.com/hop-protocol/hop-airdrop/master/src/data/eligibleAddresses.txt) that passed the project's Sybil filter |
| **total** | **60** | |

Each entry carries: `address`, `chains` it operates on, `label`,
`label_basis`, `label_source` (URL), and a `note`.

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
