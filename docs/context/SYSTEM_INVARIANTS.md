# System Invariants (Hard Laws)

These are non-negotiable system laws. If implementation, plans, or prompts conflict with these, these laws win.

## Enforcement Sources

- Schemas (shape enforcement): `schemas/*.schema.json`
- Runtime validation code: `validation/validators.py`
- Contract fixtures/tests: `tests/fixtures/`, `tests/test_contract_fixtures.py`
- Invariant test mapping: `docs/reference/TEST_STRATEGY.md`

## Invariant Registry

| ID | Hard Law | Enforcement Pointers (schema / code / tests) |
| --- | --- | --- |
| GI-1 | No answer generation without selected evidence; insufficient evidence must be explicit. | Schema: `schemas/query-response.schema.json` (`limitations`, evidence-bearing response). Code: query orchestrator + validation layer. Tests: `docs/reference/TEST_STRATEGY.md` (GI-1). |
| GI-2 | Retrieval is multi-document by default unless explicitly scoped. | Schema: `schemas/query-request.schema.json` (`scope` optional). Code: scope resolver + retrieval adapter. Tests: `docs/reference/TEST_STRATEGY.md` (GI-2). |
| GI-3 | Retrieval/evidence assembly must be deterministic for same input/state/config. | Schema: n/a. Code: retrieval adapter + evidence builder/reranker deterministic logic. Tests: `docs/reference/TEST_STRATEGY.md` (GI-3). |
| GI-4 | Every non-trivial claim must cite resolvable evidence IDs. | Schema: `schemas/model-answer.schema.json`, `schemas/query-response.schema.json`. Code: `validate_citation_integrity`. Tests: `tests/test_contract_fixtures.py` + strategy GI-4. |
| GI-5 | Text and visual evidence are both first-class; no text-only assumption. | Schema: `schemas/evidence-item.schema.json` (`asset_type` enum). Code: candidate normalization + evidence builder. Tests: strategy GI-5. |
| IM-1 | Required provenance metadata must exist by modality. | Schema: `schemas/evidence-item.schema.json`. Code: ingestion mapping + `validate_evidence_item`. Tests: fixture tests + strategy IM-1. |
| IM-2 | Metadata must stay within platform limits. | Schema: partially implicit. Code: ingestion metadata budgeting logic. Tests: strategy IM-2. |
| IM-3 | Provenance must remain joinable across stages. | Schema: evidence item fields. Code: normalization/serialization path. Tests: strategy IM-3. |
| IM-4 | `doc_id` semantics must stay stable across ingestion, retrieval, and citations; `doc_id` must come from provenance metadata, not parsed from asset S3 key shape. | Schema: request/evidence/response schemas (`doc_id`, scoped fields). Code: scoping + evidence assembly. Tests: strategy IM-4. |
| RI-1 | Unscoped requests must not pre-filter by `doc_id`. | Schema: `scope` optional in request schema. Code: retrieval adapter request construction. Tests: strategy RI-1. |
| RI-2 | `doc_id` filtering only when scope is explicit. | Schema: `schemas/query-request.schema.json` (`scope.doc_ids`, `scope_reason`). Code: scope resolver. Tests: strategy RI-2. |
| RI-3 | Retrieval rank/score/provenance needed downstream must be preserved. | Schema: n/a. Code: retrieval candidate mapper + evidence builder inputs. Tests: strategy RI-3. |
| RI-4 | Zero-candidate path is retrieval/evidence insufficiency, not generation failure. | Schema: response limitations/meta. Code: query orchestration failure handling. Tests: strategy RI-4. |
| EI-1 | All selected evidence normalizes to canonical evidence item model with unique request-local IDs. | Schema: `schemas/evidence-item.schema.json` + ID patterns in model/response schemas. Code: normalization + ID assignment + `validate_evidence_item`. Tests: fixture tests + strategy EI-1. |
| EI-2 | Dedup keys are `(doc_id, chunk_id)` for text and `(doc_id, asset_id)` for visuals. | Schema: evidence identity fields. Code: evidence dedup stage. Tests: strategy EI-2. |
| EI-3 | Enforce dominance/diversity behavior in unscoped mode. | Schema: n/a. Code: evidence builder cap/diversity rules. Tests: strategy EI-3. |
| EI-4 | Bundle size limits must always be respected. | Schema: n/a. Code: evidence bundle sizing logic. Tests: strategy EI-4. |
| EI-5 | Bundle selection and tie-breaking must be deterministic/explainable. | Schema: n/a. Code: reranker scoring + deterministic tie-break logic. Tests: strategy EI-5. |
| EI-6 | Returned evidence must include sufficient provenance for citation/audit. | Schema: `schemas/evidence-item.schema.json`. Code: evidence serializer + response builder. Tests: fixture tests + strategy EI-6. |
| RR-1 | Reranking must be LLM-independent. | Schema: n/a. Code: reranker module boundaries. Tests: strategy RR-1. |
| RR-2 | Reranking signals must be deterministic. | Schema: n/a. Code: signal computation functions. Tests: strategy RR-2. |
| RR-3 | Comparison queries prefer cross-doc support when available unless explicitly scoped. | Schema: n/a. Code: reranking heuristics. Tests: strategy RR-3. |
| MG-1 | Model context must be evidence-bounded. | Schema: indirect via output contracts. Code: prompt/invocation builder. Tests: strategy MG-1. |
| MG-2 | Model output must be JSON and schema-valid. | Schema: `schemas/model-answer.schema.json`. Code: `validate_model_answer`. Tests: fixture tests + strategy MG-2. |
| MG-3 | Citation references and `used_evidence_ids` must resolve to selected evidence IDs. | Schema: ID formats in model/response schemas. Code: `validate_citation_integrity`. Tests: fixture tests + strategy MG-3. |
| MG-4 | Insufficient evidence must be preserved; no forced certainty/fabricated citations. | Schema: model/response limitations fields. Code: orchestration + citation integrity checks. Tests: strategy MG-4. |
| MG-5 | Visual access must use short-lived presigned URLs with minimal access. | Schema: `presigned_url` field in evidence schema. Code: presign helper + API layer. Tests: strategy MG-5. |
| AR-1 | Successful responses must follow canonical response shape. | Schema: `schemas/query-response.schema.json`. Code: `validate_query_response`. Tests: fixture tests + strategy AR-1. |
| AR-2 | Evidence/response/citation consistency must hold. | Schema: response + evidence schemas. Code: `validate_citation_integrity`, response builder. Tests: fixture tests + strategy AR-2. |
| AR-3 | Scoped vs unscoped mode must be observable in response/debug path. | Schema: response `meta` fields. Code: response metadata assembly. Tests: strategy AR-3. |
| OI-1 | Failures must be attributable to a concrete pipeline stage. | Schema: n/a. Code: stage-annotated logging/telemetry. Tests: strategy OI-1. |
| OI-2 | Multi-document contribution must be measurable per request. | Schema: response `meta.docs_contributing` (when included). Code: telemetry + response metadata assembly. Tests: strategy OI-2. |
| OI-3 | Citation validation failures must be categorized and tracked. | Schema: n/a. Code: validation error categorization/logging. Tests: strategy OI-3. |

## Change Control

Any change affecting retrieval defaults, evidence assembly, generation constraints, citations, output contracts, or observability semantics must:

1. Update affected schema files in `schemas/` where shape changes are required.
2. Update code enforcement points in runtime modules (`validation/`, query orchestration, retrieval/evidence layers).
3. Update this invariant registry if a law changes.
4. Update invariant mappings in `docs/reference/TEST_STRATEGY.md`.
5. Add or update automated tests.
