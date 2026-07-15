# Test map

An honest inventory of every test in the suite (192 test functions across 26
files), what each verifies, its depth, and whether it touches real
infrastructure or mocks. The goal is to know what we actually have — gaps and
weak spots are flagged, not defended.

> Counts below are **test functions** (`def test_…`). `pytest` collects 197
> test *cases* because one function (`test_is_valid_evm_wallet_rejects_malformed`)
> is parametrized over 6 inputs.
>
> **Update (test-map fixes applied):** the migration, scheduler, tautology,
> and silent-skip findings from the first pass have been addressed — see the
> per-file notes and the "Known test coverage limits" section at the end.

## Depth-level definitions (as used below)

- **unit** — pure functions / in-memory logic; no DB, no network, no app.
- **integration** — exercises a real local dependency (Postgres and/or the
  FastAPI app via `TestClient` and/or real Redis) and/or wires multiple
  components together. Provider HTTP is **always mocked** (respx), so these
  are "integration against local infra + a fake Etherscan," never live.
- **chaos** — fault injection: the test's primary purpose is a failure /
  degradation / isolation path (provider errors, DB down, Redis down,
  per-stage failure isolation, retries).
- **live-smoke** — actually calls an external third party. **There are zero
  of these in the automated suite** (by design — CI cannot hit Etherscan).
  The live end-to-end checks live in `docs/validation.md` and were run by
  hand, not by pytest.

"Real/mock" column legend: `pure` (no I/O) · `real DB` (Postgres) ·
`mock HTTP` (respx fake Etherscan) · `real Redis` · `fake Redis` /
`failing Redis` (hand-rolled) · `mock DB` (MagicMock) · `subprocess`.

---

## tests/test_config.py — settings & production guard

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_api_key_set_parses_csv | CSV API-key list parses & trims to a set | unit | pure |
| test_validate_runtime_allows_dev_default_in_development | dev key OK outside prod | unit | pure |
| test_validate_runtime_rejects_weak_keys_in_production | weak key in prod raises | unit | pure |
| test_validate_runtime_rejects_empty_keys_in_production | empty keys in prod raises | unit | pure |
| test_validate_runtime_accepts_strong_key_in_production | strong key in prod OK | unit | pure |
| test_create_app_raises_on_weak_production_config | app factory enforces the guard | unit | pure |

## tests/test_db.py — ORM schema & session wiring

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_all_tables_registered | all 8 tables registered on the metadata | unit | pure |
| test_models_expose_expected_columns | api_keys hashes; proof/features are jsonb | unit | pure |
| test_engine_and_sessionmaker_are_lazy_and_cached | engine/sessionmaker are cached singletons | unit | pure (no connect) |
| test_get_db_yields_and_closes_session | get_db dependency yields then closes | unit | pure (no connect) |

## tests/test_migrations.py — Alembic migration path (added: item 1)

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_migrations_apply_to_head_cleanly | `alembic upgrade head` applies on a fresh DB; alembic_version at head | integration | real DB (alembic) |
| test_migration_schema_matches_orm_models | migrated schema == create_all schema (tables + columns) — drift guard | integration | real DB (alembic) |

## tests/test_health.py

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_health_returns_ok | GET /health returns 200 {"status":"ok"} | integration | app (TestClient) |

## tests/test_scoring.py — rule engine (all pure)

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_rule_new_wallet | new-wallet rule threshold | unit | pure |
| test_rule_low_activity | low-activity rule threshold | unit | pure |
| test_rule_low_diversity | low-diversity rule threshold | unit | pure |
| test_rule_bot_burst | bot-burst rule threshold | unit | pure |
| test_rule_dormant | dormancy rule | unit | pure |
| test_none_values_treated_as_zero | NULL feature cols don't crash rules | unit | pure |
| test_strong_human_has_no_flags | clean profile → no flags | unit | pure |
| test_sybil_suspected_when_multiple_signals | ≥2 signals → sybil_suspected | unit | pure |
| test_single_signal_is_not_sybil | 1 signal → not sybil | unit | pure |
| test_graph_cluster_rule_fires_on_graph_evidence | graph evidence → sybil_cluster | unit | pure |
| test_graph_cluster_rule_absent_without_evidence | no evidence → no cluster flag | unit | pure |
| test_graph_ablation_switch_disables_cluster_flag | use_graph=False removes flag & lowers score | unit | pure |
| test_bucketing_thresholds | likelihood/tier bucket boundaries | unit | pure |
| test_strong_human_scores_high_gold | strong profile → high/gold | unit | pure |
| test_empty_wallet_scores_low_bronze_with_flags | empty → low/bronze + flags | unit | pure |
| test_confidence_clamped_and_deterministic | score in [0,1] and deterministic | unit | pure |

## tests/test_validation.py — shared wallet validator (H2)

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_is_valid_evm_wallet_accepts_canonical | canonical address accepted | unit | pure |
| test_is_valid_evm_wallet_rejects_malformed | 6 malformed forms rejected (parametrized) | unit | pure |
| test_require_valid_wallet_passes_for_valid | valid address → no raise | unit | pure |
| test_require_valid_wallet_raises_for_invalid | invalid → InvalidWalletError | unit | pure |

## tests/test_proof_canonical.py — canonical serialization (all pure)

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_proof_dto_accessors | Proof DTO exposes payload fields | unit | pure |
| test_verification_result_defaults | VerificationResult defaults (key_id None) | unit | pure |
| test_canonical_is_key_order_independent | sorted keys → identical bytes | unit | pure |
| test_canonical_has_no_whitespace_and_sorted_keys | exact canonical byte form | unit | pure |
| test_build_payload_has_exact_fields | payload has exactly the signed field set | unit | pure |

## tests/test_split.py — train/test split (all pure)

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_split_is_deterministic | build_split is deterministic | unit | pure (file) |
| test_committed_split_matches_regeneration | committed split == regenerated (no drift) | unit | pure (file) |
| test_no_wallet_in_both_splits | train/test disjoint | unit | pure (file) |
| test_split_covers_all_wallets_once | union == all wallets, no loss | unit | pure (file) |
| test_no_cluster_spans_both_splits | Sybil clusters don't leak across the split | unit | pure (file) |
| test_split_is_stratified_and_roughly_70_30 | both classes present; ~30% held out | unit | pure (file) |

## tests/test_seed.py — dataset & seeding

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_dataset_is_well_formed | every entry has valid address/label/source/cluster | unit | pure (file) |
| test_dataset_is_balanced_and_unique | ≥30 per class, no duplicates | unit | pure (file) |
| test_seed_registers_wallets_without_provider | seed registers all wallets, no tx (no key) | integration | real DB |
| test_seed_is_idempotent | re-seed doesn't duplicate wallet rows | integration | real DB |
| test_dataset_chain_values_are_supported | every chain value is a supported Chain | unit | pure (file) |

## tests/test_evaluate.py — evaluation harness

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_predict_label | likelihood→label mapping | unit | pure |
| test_accuracy_and_confusion | accuracy + confusion matrix math | unit | pure |
| test_precision_recall | precision/recall incl. empty-denominator | unit | pure |
| test_render_report_contains_key_sections | report markdown has expected sections | unit | pure |
| test_render_report_without_ablation | ablation section omitted when absent | unit | pure |
| test_cluster_summary_reports_counts | cluster summary string has counts | unit | pure |
| test_split_rows_partitions_by_committed_split | rows partitioned by committed split | unit | pure (file) |
| test_evaluate_scores_seeded_wallets | 2 seeded wallets → accuracy 1.0 | integration | real DB |
| test_evaluate_uses_empty_features_when_missing | missing features → low → sybil | integration | real DB |
| test_prepare_wallet_skips_when_features_exist | existing features → no ingest | integration | real DB |
| test_prepare_wallet_skips_without_provider | no provider → no ingest | integration | real DB |
| test_prepare_wallet_ingests_all_chains | ingests ETH + Arbitrum on demand | integration | real DB + mock HTTP |
| test_prepare_wallet_handles_ingestion_error | provider error caught, no crash | chaos | real DB + mock HTTP |
| test_load_dataset_reads_committed_file | dataset loads, both classes | unit | pure (file) |

## tests/test_features.py — behavioral feature computation

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_features_on_normal_wallet | all 10 features on a normal wallet | integration | real DB |
| test_features_on_dormant_wallet | recency/dormancy/age on stale wallet | integration | real DB |
| test_features_on_burst_wallet | burst score + activity ratios | integration | real DB |
| test_features_on_empty_wallet | zero-tx wallet → zero features | integration | real DB |
| test_features_are_persisted_and_idempotent | upsert, no duplicate feature rows | integration | real DB |
| test_features_from_ingested_data | ingest (mock) → compute features | integration | real DB + mock HTTP |
| test_compute_features_for_wallets_isolates_failures | one wallet's failure isolated in batch | chaos | real DB (injected error) |
| test_all_wallet_ids_with_transactions | lists only wallets that have txs | integration | real DB |

## tests/test_graph.py — graph/cluster features

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_graph_features_on_cluster_and_isolated | cluster size, shared funder, overlap, depth | integration | real DB |
| test_graph_depth_is_cycle_safe | mutual funding doesn't infinite-loop | chaos | real DB |
| test_graph_depth_diamond_uses_memo | diamond funding depth via memo | integration | real DB |
| test_graph_ignores_null_counterparty | null counterparty skipped | integration | real DB |

## tests/test_ingestion_etl.py — transform (pure) + load (DB)

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_transform_classifies_out | outbound tx classified | unit | pure |
| test_transform_classifies_in_and_self | inbound & self-transfer classified | unit | pure |
| test_transform_contract_creation_uses_contract_address | contract-creation counterparty | unit | pure |
| test_transform_skips_malformed_and_unrelated_rows | bad/unrelated rows dropped | unit | pure |
| test_classify_neither_party_defaults_to_out | defensive default branch | unit | pure |
| test_load_persists_and_sets_aggregates | load persists txs + wallet aggregates | integration | real DB |
| test_load_is_idempotent | re-load inserts nothing | integration | real DB |
| test_load_adds_only_new_transactions_on_partial_overlap | only new txs inserted | integration | real DB |
| test_load_dedupes_within_batch | duplicate tx_hash in batch deduped | integration | real DB |
| test_load_handles_full_uint256_value | max uint256 value survives numeric column | integration | real DB |

## tests/test_ingestion_provider.py — Etherscan client (HTTP always mocked)

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_happy_path_returns_raw_transactions | success returns raw list | integration | mock HTTP |
| test_no_transactions_found_returns_empty | "no transactions" → [] | integration | mock HTTP |
| test_persistent_429_retries_then_raises_data_unavailable | 429 retried to max then DataUnavailable | chaos | mock HTTP |
| test_rate_limit_message_recovers_after_retry | rate-limit body retried, then recovers | chaos | mock HTTP |
| test_timeout_is_retried_then_surfaced | timeout retried then surfaced | chaos | mock HTTP |
| test_provider_error_not_retried | non-transient error not retried | chaos | mock HTTP |
| test_http_500_is_transient_then_data_unavailable | 5xx retried then DataUnavailable | chaos | mock HTTP |
| test_unexpected_status_code_is_provider_error | 4xx (non-429) → ProviderError, no retry | chaos | mock HTTP |
| test_transport_error_is_retried | connect error retried | chaos | mock HTTP |
| test_generic_http_error_is_provider_error | generic HTTP error not retried | chaos | mock HTTP |
| test_injected_client_is_not_closed_by_context | injected client not closed by us | integration | mock HTTP |
| test_unsupported_chain_raises_provider_error | unknown chain id → ProviderError | unit | pure (monkeypatch) |
| test_request_without_initialized_client_raises | no client → ProviderError | unit | pure |
| test_supports_ethereum_and_arbitrum | supported-chain check | unit | pure |
| test_chainid_param_matches_chain | correct chainid per chain in request | integration | mock HTTP |

## tests/test_ingestion_service.py — fetch/cache/orchestration

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_fetch_requires_configured_provider | no key → ProviderError | unit | pure |
| test_fetch_rejects_unsupported_chain | unsupported chain → ProviderError | unit | pure (monkeypatch) |
| test_fetch_caches_and_serves_from_cache | 2nd fetch served from cache (1 HTTP call) | integration | mock HTTP + fake cache |
| test_fetch_degrades_gracefully_when_cache_unavailable | Redis down → still fetches | chaos | mock HTTP + failing cache |
| test_fetch_uses_injected_client | injected client path | integration | mock HTTP |
| test_build_cache_returns_client_when_enabled | cache built only when TTL>0 | unit | pure |
| test_encode_decode_round_trip | tx JSON round-trip (uint256, null cp) | unit | pure |
| test_ingest_wallet_persists | full ETL persists 2 txs | integration | real DB + mock HTTP |

## tests/test_jobs.py — compute_features CLI

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_run_no_wallets_returns_empty | no wallets → {} | integration | real DB |
| test_run_all_wallets_with_transactions | computes features for all with txs | integration | real DB |
| test_run_specific_wallet_ids | computes only requested ids | integration | real DB |
| test_main_computes_features | CLI main runs over all wallets | integration | real DB |

## tests/test_pipeline.py — end-to-end scoring pipeline

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_score_wallet_happy_writes_history | ingest→feature→score→persist writes history | integration | real DB + mock HTTP |
| test_score_wallet_rejects_invalid_address | bad address fails at validate, no persist (H2) | integration | real DB |
| test_batch_rejects_invalid_address_but_scores_valid | bad rejected, good scored in same batch (H2) | integration | real DB + mock HTTP |
| test_batch_isolates_a_failing_wallet | one ingest failure isolated, batch continues | chaos | real DB + mock HTTP |
| test_feature_stage_failure_is_isolated | feature-stage error isolated | chaos | real DB + mock HTTP |
| test_score_stage_failure_is_isolated | score-stage error isolated | chaos | real DB + mock HTTP |
| test_persist_stage_failure_is_isolated | persist-stage error isolated | chaos | real DB + mock HTTP |
| test_pipeline_emits_structured_stage_logs | all 5 stages emit ok JSON logs | integration | real DB + mock HTTP |
| test_pipeline_logs_stage_error_and_batch_summary | error log + batch_summary emitted | chaos | real DB + mock HTTP |
| test_persist_is_append_only_per_scorer_version | upsert per version; new version → new row | integration | real DB |
| test_known_and_stale_wallet_helpers | known/stale address queries | integration | real DB |

## tests/test_worker.py — background worker

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_ingest_wallets_success | batch ingest both wallets | integration | real DB + mock HTTP |
| test_ingest_wallets_skips_invalid_address | malformed address skipped, no HTTP (H2) | integration | real DB |
| test_ingest_wallets_isolates_failures | provider error per wallet isolated | chaos | real DB + mock HTTP |
| test_ingest_wallets_isolates_unexpected_errors | unexpected error isolated + rollback | chaos | real DB (injected error) |
| test_refresh_all_no_wallets | empty DB → {} | integration | real DB |
| test_refresh_all_ingests_known_wallets | refresh known wallets + features | integration | real DB + mock HTTP |
| test_ingest_single | single-wallet ingest + features | integration | real DB + mock HTTP |
| test_ingest_single_provider_failure_creates_no_features | provider fail → no feature row | chaos | real DB + mock HTTP |
| test_main_once | --once dispatches refresh_all | unit | monkeypatch |
| test_main_wallet | --wallet dispatches ingest_single | unit | monkeypatch |
| test_main_scheduled_wires_and_triggers_scoring | scheduler wires scheduled_score (not refresh_all); firing it invokes score_wallets (item 2) | unit | fake scheduler + monkeypatch |

## tests/test_score_job.py — scoring CLI + scheduled_score

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_resolve_wallet_mode | --wallet resolves to [addr] | unit | pure (parser) |
| test_resolve_batch_mode | --batch reads file lines | unit | pure (parser+file) |
| test_resolve_refresh_all_mode | --refresh-all lists known wallets | integration | real DB |
| test_resolve_refresh_stale_mode | --refresh-stale lists stale wallets | integration | real DB |
| test_run_rejects_invalid_address | bad address fails at validate stage (H2) | integration | real DB |
| test_run_scores_and_persists | run scores + writes 1 history row | integration | real DB + mock HTTP |
| test_main_refresh_all_empty_db | CLI main on empty DB, no error | integration | real DB |
| test_scheduled_score_no_stale_wallets | no stale → zero summary | integration | real DB |
| test_scheduled_score_scores_stale_wallets | stale wallet scored + persisted | integration | real DB + mock HTTP |

## tests/test_metrics.py — Redis-backed metrics (H1)

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_record_and_snapshot | record/snapshot counters + min/max/avg | integration | real Redis |
| test_render_prometheus_format | Prometheus TYPE/HELP/value lines | integration | real Redis |
| test_metrics_endpoint_empty | /metrics reads 0 after reset | integration | real Redis + app |
| test_metrics_degrade_when_redis_down | Redis outage → no raise, zero snapshot | chaos | Boom (fake) client |
| test_metrics_increment_after_a_run | pipeline run reflected on /metrics | integration | real Redis + real DB + mock HTTP |
| test_metrics_visible_across_processes | child process's scoring visible via /metrics | integration | subprocess + real Redis |

## tests/test_rate_limit.py — Redis rate limiter

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_rate_limit_exceeded_returns_429 | over limit → 429 + Retry-After | integration | app + fake Redis |
| test_rate_limit_fails_open_when_redis_unavailable | Redis down → requests allowed | chaos | app + failing Redis |

## tests/test_verify.py — POST /verify

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_verify_returns_signed_assessment | response shape + real 64-byte signature | integration | app |
| test_verify_proof_is_third_party_verifiable | reconstruct canonical form → sig verifies; tamper fails | integration | app |
| test_verify_defaults_chains_to_ethereum | default chain | integration | app |
| test_verify_invalid_wallet_returns_400 | malformed wallet → 400 | integration | app |
| test_verify_malformed_body_returns_422 | missing field → 422 | integration | app |
| test_verify_missing_api_key_returns_401 | no key → 401 | integration | app |
| test_verify_invalid_api_key_returns_401 | wrong key → 401 | integration | app |
| test_verify_scores_high_for_strong_stored_features | stored strong features → high/gold | integration | real DB |
| test_verify_scores_low_when_no_data | no data → low/bronze | integration | real DB |
| test_verify_degrades_to_neutral_on_db_error | DB error → 200, neutral score | chaos | mock DB (raises) |
| test_verify_ingests_on_miss_when_provider_configured | cache miss → on-demand ingest | integration | real DB + mock HTTP |

## tests/test_proof_keys.py — Ed25519 keys + /proof/public-key

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_load_signer_from_env_is_stable | env key → stable key_id, non-ephemeral | unit | pure |
| test_sign_and_verify_round_trip | sign→verify true; tamper false | unit | pure |
| test_ephemeral_key_warns | no key → ephemeral + loud WARNING | unit | pure (caplog) |
| test_public_key_endpoint | GET /proof/public-key shape | integration | app |

## tests/test_proof_service.py — ProofService.generate + persist

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_generate_produces_verifiable_signature | generated proof verifies with pubkey | unit | pure |
| test_two_proofs_differ_but_both_verify | random nonce → distinct sigs, both verify | unit | pure |
| test_generate_persists_proof_row | proof row persisted with key_id/ttl | integration | real DB |
| test_generate_reuses_existing_wallet_row | existing wallet not duplicated | integration | real DB |

## tests/test_proof_verify.py — ProofService.verify branches

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_round_trip_valid | valid proof → ok | unit | pure |
| test_tampered_payload_is_bad_signature | payload tamper → bad_signature | unit | pure |
| test_malformed_signature_is_bad_signature | non-base64 sig → bad_signature | unit | pure |
| test_expired_proof | past expiry → expired | unit | pure |
| test_unknown_key | other key_id → unknown_key | unit | pure |
| test_canonicalization_is_order_independent | reordered payload still verifies | unit | pure |
| test_revoked_proof | revoked flag → revoked | integration | real DB |

## tests/test_proof_verify_endpoint.py — POST /proof/verify

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_proof_verify_accepts_valid_proof | round-trip a /verify response → valid/ok | integration | app |
| test_proof_verify_rejects_tampered_field | tampered field → bad_signature | integration | app |
| test_proof_verify_rejects_tampered_signature | flipped sig byte → bad_signature | integration | app |
| test_proof_verify_rejects_unknown_key | swapped key_id → unknown_key | integration | app |
| test_proof_verify_reports_revoked | revoked proof → revoked | integration | app + real DB |
| test_proof_verify_requires_api_key | no key → 401 | integration | app |

## tests/test_revoke_job.py — revocation CLI

| Test | Verifies | Depth | Real/mock |
| --- | --- | --- | --- |
| test_revoke_by_id_flips_flag | revoke by id sets revoked | integration | real DB |
| test_revoke_by_id_already_revoked_is_noop | double revoke → 0 rows | integration | real DB |
| test_revoke_by_id_unknown_returns_zero | unknown id → 0 | integration | real DB |
| test_revoke_by_wallet_revokes_all | revoke all proofs for a wallet | integration | real DB |
| test_revoke_by_wallet_unknown_returns_zero | unknown wallet → 0 | integration | real DB |
| test_run_dispatches_proof_id | run() dispatches --proof-id | integration | real DB |
| test_run_dispatches_wallet | run() dispatches --wallet | integration | real DB |
| test_main_by_proof_id | CLI main revokes by id | integration | real DB |
| test_main_by_wallet | CLI main revokes by wallet | integration | real DB |

---

## Summary

### Totals by depth level (192 test functions)

| Depth | Count | Share |
| --- | --- | --- |
| unit | 80 | 42% |
| integration | 89 | 46% |
| chaos | 23 | 12% |
| live-smoke | 0 | 0% |

Change from the first pass (net 0 functions: +2 migration tests, −2 removed
tautologies, and the scheduler test rewritten in place): unit 81→80,
integration 88→89, chaos 23.

Classification is a judgment call at the edges (e.g. a mocked-HTTP provider
test is "integration against a fake Etherscan," and error-injection tests are
counted as chaos). **Real third-party calls: 0** — every Etherscan
interaction is mocked with respx. Real local infrastructure is used heavily:
~**90** tests require Postgres, and **6** require Redis (metrics); the rest of
the Redis surface uses hand-rolled fakes. Missing Postgres/Redis is now a
**hard failure**, not a silent skip (opt out with `ALLOW_SKIP_TEST_SERVICES=1`).

### Well-protected areas (redundant / deep coverage)

- **Provider resilience** — 8 chaos tests cover 429, rate-limit body,
  timeout, 5xx, transport error, non-retryable error, unexpected status, and
  generic HTTP error. Genuinely thorough.
- **Rule engine** — 16 unit tests: every rule threshold, flag combination,
  bucketing boundary, graph ablation, and determinism.
- **Failure isolation** — pipeline (all 4 stages), worker (provider +
  unexpected), and feature batch each have dedicated isolation tests.
- **Proof verification** — every reason branch (ok / bad_signature / expired /
  unknown_key / revoked) is covered **twice**: at the service level
  (test_proof_verify) and again through the HTTP endpoint
  (test_proof_verify_endpoint). Signing/canonicalization also well covered.
- **ETL load idempotency** — re-run, partial overlap, in-batch dedupe, and
  full-uint256 all covered.
- **Auth** — 401 paths (missing/invalid key) covered on /verify and
  /proof/verify.

### Thin coverage (single test — one regression away from a blind spot)

- **Cross-process metrics (H1's core claim)** — one subprocess test
  (`test_metrics_visible_across_processes`). Concurrent-writer correctness of
  the min/max Lua is not tested (only sequential single-writer).
- **Metrics degradation** — one test (`test_metrics_degrade_when_redis_down`).
- **/verify DB-error degradation** — one test (`test_verify_degrades_to_neutral_on_db_error`).
- **Rate limiting** — only 2 tests (429 + fail-open). The **window reset**
  (429 → 200 after the minute rolls over) is not tested in pytest at all; the
  FakeRedis models no TTL, so expiry-driven reset is never exercised (only
  verified live in docs/validation.md).
- **/health** — 1 test.
- **Graph edge cases** — cycle-safety, diamond memo, and null counterparty are
  each a single test.
- **Ephemeral-key warning** — 1 test.

### Capabilities with NO direct test

1. ~~Alembic migrations~~ — **RESOLVED (item 1).** `tests/test_migrations.py`
   now asserts migrations apply to head on a fresh DB and that the migrated
   schema equals the ORM `create_all` schema (drift guard); a CI
   `migration-check` job also runs the full suite against the migrated schema.
2. **The real Etherscan contract.** Every provider test mocks HTTP; nothing in
   CI hits the live API, so a change in Etherscan's response shape would go
   undetected. (By design — covered manually in docs/validation.md.)
3. ~~APScheduler wiring / scheduled_score firing~~ — **RESOLVED (item 2).**
   `test_main_scheduled_wires_and_triggers_scoring` asserts the scheduler is
   wired to `scheduled_score` and that firing it invokes `score_wallets`.
   (The real *interval timing* of APScheduler is still not exercised — see
   Known limits.)
4. **`core/logging.py`** (`log_event`, `configure_logging`) — no dedicated
   test; exercised only indirectly (pipeline log assertions, app startup).
5. **Endpoint-level "expired"** for POST /proof/verify — service-level expiry
   is tested, but not through the HTTP endpoint.
6. **`VerifyRequest` extra-field rejection** (`extra="forbid"`) — the 422 test
   omits a required field; no test sends an unexpected extra field.
7. **OpenAPI drift** — nothing asserts `docs/openapi.json` matches the app
   (`scripts/export_openapi.py` is untested).
8. **Privacy invariant** — no explicit assertion that raw tx data (e.g. tx
   hashes) never appears in a proof/response; it's enforced structurally by
   the fixed payload schema, not by a test.

### Test-quality concerns (weak assertions / over-mocking / would-pass-if-broken)

- **[A] Migrations untested** — **RESOLVED (item 1).** See gap #1.
- **[B] `test_scheduled_score_uses_score_wallets_symbol`** (tautology) —
  **REMOVED (item 3).**
- **[C] `test_main_scheduled`** (fake scheduler, wrong function) — **FIXED
  (item 2):** replaced by a test that asserts the correct job is wired and
  actually invokes `score_wallets`.
- **[D] `test_verify_is_deterministic`** (always "low", no DB) — **REMOVED
  (item 3).** Real determinism remains covered in test_scoring.
- **[E] `test_verify_proof_is_third_party_verifiable`** reconstructs the
  payload with the production `build_payload`/`canonical_bytes`, so it proves
  an internal round-trip but not independence from the app's own
  canonicalization. **Accepted as a known limit** (see below) — the genuinely
  independent verifier lives in docs/validation.md (manual).
- **[F] Rate-limit reset path** is not unit-tested (FakeRedis has no TTL).
  **Accepted as a known limit** — covered implicitly by the CI Redis service /
  the live validation.
- **[G] Loose numeric assertions** in test_graph (`>= 0.33`, `> 0.3`) accept a
  band rather than an exact value. (Unchanged — low risk; graph scores are
  heuristic.)
- **[H] Evaluate/accuracy tests** assert accuracy 1.0 on 2 hand-picked wallets
  — they validate harness plumbing, not the honest held-out accuracy (~78.6%),
  which is an offline result appropriately kept out of unit tests. (Unchanged.)
- **[I] Infra-dependent silent "green"** — **RESOLVED (item 4):** a missing
  Postgres/Redis is now a hard failure with an actionable message, so the
  suite can no longer report green while skipping the integration/chaos layer.
  Explicit opt-out: `ALLOW_SKIP_TEST_SERVICES=1`.

### Known test coverage limits

Deliberately-accepted limits (not planned for further work right now):

- **Rate-limit TTL reset is not directly unit-tested.** The FakeRedis used in
  `test_rate_limit.py` models no key expiry, so the fixed-window reset
  (429 → 200 after the minute rolls over) is not asserted in pytest. It is
  covered implicitly by running against the real Redis service in CI and was
  verified end-to-end in docs/validation.md.
- **Cross-process metrics has a single but heavyweight test.**
  `test_metrics_visible_across_processes` spawns a real child process that
  records a scoring event and asserts the API process's `/metrics` reflects it
  via shared Redis. One test, but it exercises the real cross-process path —
  considered sufficient. (Concurrent-writer min/max correctness is not
  separately stress-tested.)
- **Proof cross-language independence is out of scope.** The in-suite proof
  tests prove a round-trip but reuse the in-app canonicalization
  (`build_payload`/`canonical_bytes`); they do not prove a non-Python verifier
  can reproduce the canonical bytes. An independent verifier was exercised
  manually in docs/validation.md.
- **APScheduler interval timing** is not exercised — only that the correct job
  is registered and that invoking it runs the pipeline.

### Bottom line

The **logic layers are well tested** (rules, canonicalization, ETL,
resilience, failure isolation, proof verification), and the **operational-glue
gaps flagged in the first pass are now closed**: migrations are verified
against the ORM (and run in CI), the scheduled-scoring wiring is genuinely
asserted, the two tautological tests are gone, and a missing service fails
loudly instead of silently skipping. The remaining items are documented,
deliberately-accepted limits (rate-limit TTL reset, single cross-process
metrics test, proof cross-language independence, scheduler interval timing) —
none are logic bugs today.
