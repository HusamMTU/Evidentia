# Test Strategy (Reference, Non-Authoritative)

This document is guidance; if it conflicts with code/contracts/tests, those win.

This strategy maps canonical invariants in `docs/context/SYSTEM_INVARIANTS.md` to executable tests.

## Authority Boundaries

If this document conflicts with implementation reality, follow:

- Executable tests in `tests/`
- Schemas in `schemas/`
- Runtime validation logic in `validation/`
- Hard laws in `docs/context/SYSTEM_INVARIANTS.md`

## Current Implemented Contract Tests

- `tests/test_contract_fixtures.py`
- `tests/fixtures/query-request.unscoped.valid.json`
- `tests/fixtures/query-request.scoped.valid.json`
- `tests/fixtures/model-answer.valid.json`
- `tests/fixtures/evidence-item.text.valid.json`
- `tests/fixtures/evidence-item.visual.valid.json`
- `tests/fixtures/query-response.valid.json`

## Invariant Coverage Matrix

Every invariant must map to at least one automated test. Matrix below is the canonical mapping plan.

| Invariant ID | Unit Coverage | Integration Coverage | E2E Coverage |
| --- | --- | --- | --- |
| GI-1 | `tests/unit/test_answer_orchestration.py::test_refuses_generation_on_empty_bundle` | `tests/integration/test_api_query_handler.py::test_retrieval_empty_returns_insufficient_evidence` | `tests/e2e/test_insufficient_evidence.py::test_no_unsupported_answer` |
| GI-2 | `tests/unit/test_scoping.py::test_defaults_unscoped` | `tests/integration/test_retrieval_adapter.py::test_unscoped_no_doc_filter` | `tests/e2e/test_multidoc_queries.py::test_multidoc_default` |
| GI-3 | `tests/unit/test_evidence_builder_determinism.py::test_same_input_same_bundle` | `tests/integration/test_evidence_builder_pipeline.py::test_repeatable_selection` | `tests/e2e/test_multidoc_queries.py::test_repeatability_on_fixed_corpus` |
| GI-4 | `tests/unit/test_citation_validation.py::test_rejects_missing_ids` | `tests/integration/test_claude_response_validation.py::test_rejects_unresolvable_citation` | `tests/e2e/test_multidoc_queries.py::test_all_citations_resolve` |
| GI-5 | `tests/unit/test_candidate_normalization.py::test_supports_text_and_visual` | `tests/integration/test_evidence_builder_pipeline.py::test_mixed_modality_bundle` | `tests/e2e/test_visual_queries.py::test_visual_question_uses_visual_evidence` |
| IM-1 | `tests/unit/test_metadata_validation.py::test_required_provenance_keys` | `tests/integration/test_ingestion_verification.py::test_reports_missing_fields` | `tests/e2e/test_ingestion_smoke.py::test_ingested_items_have_required_metadata` |
| IM-2 | `tests/unit/test_metadata_budget.py::test_enforces_size_and_key_limits` | `tests/integration/test_ingestion_verification.py::test_rejects_oversized_metadata` | `tests/e2e/test_ingestion_smoke.py::test_metadata_budget_respected` |
| IM-3 | `tests/unit/test_evidence_serialization.py::test_preserves_provenance` | `tests/integration/test_evidence_builder_pipeline.py::test_provenance_survives_normalization` | `tests/e2e/test_multidoc_queries.py::test_provenance_present_in_response` |
| IM-4 | `tests/unit/test_scoping.py::test_doc_id_semantics_consistent` | `tests/integration/test_retrieval_adapter.py::test_scope_matches_ingestion_doc_ids` | `tests/e2e/test_multidoc_queries.py::test_doc_id_stability_end_to_end` |
| RI-1 | `tests/unit/test_scoping.py::test_unscoped_mode_without_scope_field` | `tests/integration/test_retrieval_adapter.py::test_no_prefilter_in_unscoped_mode` | `tests/e2e/test_multidoc_queries.py::test_unscoped_includes_multiple_docs` |
| RI-2 | `tests/unit/test_scoping.py::test_explicit_scope_only_from_request_scope` | `tests/integration/test_retrieval_adapter.py::test_scoped_filters_requested_docs_only` | `tests/e2e/test_multidoc_queries.py::test_scoped_excludes_out_of_scope_docs` |
| RI-3 | `tests/unit/test_candidate_normalization.py::test_preserves_rank_and_score` | `tests/integration/test_evidence_builder_pipeline.py::test_rank_score_available_downstream` | `tests/e2e/test_multidoc_queries.py::test_retrieval_debug_contains_provenance` |
| RI-4 | `tests/unit/test_failure_classification.py::test_zero_candidates_classified_as_retrieval_insufficiency` | `tests/integration/test_api_query_handler.py::test_zero_candidates_not_generation_error` | `tests/e2e/test_insufficient_evidence.py::test_stage_attribution_retrieval` |
| EI-1 | `tests/unit/test_candidate_normalization.py::test_maps_to_evidence_schema` | `tests/integration/test_evidence_builder_pipeline.py::test_unique_request_local_ids` | `tests/e2e/test_multidoc_queries.py::test_evidence_ids_present_and_unique` |
| EI-2 | `tests/unit/test_deduplication.py::test_text_dedup_by_doc_chunk` | `tests/integration/test_evidence_builder_pipeline.py::test_dedup_runs_before_id_finalization` | `tests/e2e/test_multidoc_queries.py::test_no_duplicate_evidence_items` |
| EI-3 | `tests/unit/test_bundle_caps.py::test_per_doc_caps_enforced_unscoped` | `tests/integration/test_evidence_builder_pipeline.py::test_scoped_mode_bypasses_cross_doc_diversity_rule` | `tests/e2e/test_multidoc_queries.py::test_unscoped_avoids_single_doc_dominance` |
| EI-4 | `tests/unit/test_bundle_caps.py::test_global_visual_cap_enforced` | `tests/integration/test_evidence_builder_pipeline.py::test_bundle_size_limits_respected` | `tests/e2e/test_visual_queries.py::test_visual_count_never_exceeds_cap` |
| EI-5 | `tests/unit/test_reranking.py::test_deterministic_tiebreak` | `tests/integration/test_evidence_builder_pipeline.py::test_selected_bundle_matches_scores` | `tests/e2e/test_multidoc_queries.py::test_selection_stable_on_fixed_corpus` |
| EI-6 | `tests/unit/test_evidence_serialization.py::test_required_provenance_fields_present` | `tests/integration/test_api_query_handler.py::test_response_contains_expected_provenance` | `tests/e2e/test_multidoc_queries.py::test_provenance_returned_for_cited_items` |
| RR-1 | `tests/unit/test_reranking.py::test_no_model_client_dependency` | `tests/integration/test_evidence_builder_pipeline.py::test_reranker_runs_without_model` | `tests/e2e/test_multidoc_queries.py::test_reranking_path_independent_from_generation` |
| RR-2 | `tests/unit/test_reranking.py::test_signal_functions_deterministic` | `tests/integration/test_evidence_builder_pipeline.py::test_combined_score_stability` | `tests/e2e/test_multidoc_queries.py::test_repeatable_rank_order` |
| RR-3 | `tests/unit/test_reranking.py::test_cross_doc_support_boost_for_comparison_queries` | `tests/integration/test_evidence_builder_pipeline.py::test_scoped_query_no_out_of_scope_boost` | `tests/e2e/test_multidoc_queries.py::test_comparison_prefers_cross_doc_bundle` |
| MG-1 | `tests/unit/test_prompt_builder.py::test_only_selected_evidence_in_prompt` | `tests/integration/test_claude_response_validation.py::test_invocation_excludes_unselected_candidates` | `tests/e2e/test_multidoc_queries.py::test_answer_bounded_to_selected_evidence` |
| MG-2 | `tests/unit/test_response_schema_validation.py::test_rejects_non_json_and_schema_invalid_output` | `tests/integration/test_claude_response_validation.py::test_retries_then_fails_cleanly` | `tests/e2e/test_insufficient_evidence.py::test_invalid_output_not_returned_to_client` |
| MG-3 | `tests/unit/test_citation_validation.py::test_rejects_unknown_citation_and_used_ids` | `tests/integration/test_claude_response_validation.py::test_blocks_invalid_citation_response` | `tests/e2e/test_multidoc_queries.py::test_used_and_cited_ids_resolve` |
| MG-4 | `tests/unit/test_response_schema_validation.py::test_accepts_structured_insufficient_evidence` | `tests/integration/test_api_query_handler.py::test_preserves_limitations_from_model` | `tests/e2e/test_insufficient_evidence.py::test_no_fabricated_citations_when_evidence_low` |
| MG-5 | `tests/unit/test_presign.py::test_ttl_capped` | `tests/integration/test_api_query_handler.py::test_visual_payload_uses_presigned_urls` | `tests/e2e/test_visual_queries.py::test_presigned_urls_short_lived` |
| AR-1 | `tests/unit/test_response_schema_validation.py::test_response_serializer_required_fields` | `tests/integration/test_api_query_handler.py::test_success_response_validates_against_schema` | `tests/e2e/test_multidoc_queries.py::test_response_shape_valid` |
| AR-2 | `tests/unit/test_citation_validation.py::test_used_ids_subset_and_evidence_id_uniqueness` | `tests/integration/test_api_query_handler.py::test_rejects_citation_evidence_mismatch` | `tests/e2e/test_multidoc_queries.py::test_response_consistency` |
| AR-3 | `tests/unit/test_response_schema_validation.py::test_scope_meta_fields_shape` | `tests/integration/test_api_query_handler.py::test_scope_mode_exposed_in_meta` | `tests/e2e/test_multidoc_queries.py::test_scoped_unscoped_markers_present` |
| OI-1 | `tests/unit/test_observability_contract.py::test_stage_codes_enum` | `tests/integration/test_observability.py::test_failure_paths_emit_stage_attribution` | `tests/e2e/test_observability_e2e.py::test_induced_failures_map_to_single_stage` |
| OI-2 | `tests/unit/test_observability_contract.py::test_docs_contributing_metric_shape` | `tests/integration/test_observability.py::test_docs_contributing_emitted` | `tests/e2e/test_observability_e2e.py::test_multidoc_queries_emit_docs_contributing` |
| OI-3 | `tests/unit/test_citation_validation.py::test_error_codes_categorized` | `tests/integration/test_observability.py::test_citation_errors_increment_metrics_by_category` | `tests/e2e/test_observability_e2e.py::test_invalid_citations_surface_observable_signals` |

## Coverage Rule

- A change to any invariant (`GI-*`, `IM-*`, `RI-*`, `EI-*`, `RR-*`, `MG-*`, `AR-*`, `OI-*`) must update this matrix and corresponding automated tests.

## Suggested Suite Layout

- Unit: `tests/unit/`
- Integration: `tests/integration/`
- End-to-end: `tests/e2e/`
- Contract fixtures: `tests/fixtures/`
- Contract fixture test: `tests/test_contract_fixtures.py`
