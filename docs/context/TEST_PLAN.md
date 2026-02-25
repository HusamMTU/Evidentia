# Test Plan

This plan maps `docs/context/SYSTEM_INVARIANTS.md` to executable tests for the MVP. It is organized by test layer so the team can catch regressions early and isolate failures quickly.

## Goals

- Enforce system invariants with automated tests
- Separate deterministic pipeline failures from LLM/generation failures
- Provide repeatable regression checks for multi-document behavior and citation integrity

## Test Strategy

- Prefer deterministic unit/integration tests for retrieval, evidence builder, and validation logic.
- Use end-to-end tests for full pipeline behavior on a fixed seed corpus.
- Use golden fixtures for evidence bundles and validated JSON responses where practical.
- Track invariant coverage; each invariant should have at least one automated test.

## Test Layers

### 1. Unit Tests

Focus: pure logic and deterministic modules

- Query scoping resolver
- Candidate normalization
- Deduplication
- Bundle cap enforcement
- Reranking signals and tie-breakers
- Response schema validation
- Citation reference validation

### 2. Integration Tests

Focus: service boundaries and component wiring (without full production path)

- KB retrieval adapter mapping into candidate schema
- Evidence builder using realistic retrieval payloads
- Presigned URL generation for visual evidence
- Claude response validator on real/mocked model outputs
- API handler behavior with retrieval-only and answer-generation modes

### 3. End-to-End Tests

Focus: full query path over seed corpus

- Ingestion -> retrieval -> evidence bundle -> model -> validation -> API response
- Multi-document comparison questions
- Visual-led questions
- Insufficient evidence handling

## Test Data and Fixtures

## Seed Corpus Requirements (MVP)

- 8-20 documents total
- At least:
  - 2 text-heavy docs
  - 2 visual/diagram-heavy docs
  - 2 table-heavy docs
  - 2 overlapping-topic docs for cross-document comparison

## Fixture Types

- `query fixtures`: request payloads (scoped and unscoped)
- `retrieval fixtures`: raw KB candidate payloads
- `bundle fixtures`: expected normalized/deduped evidence bundles
- `model output fixtures`: valid JSON, malformed JSON, invalid citations, insufficient evidence
- `golden responses`: approved end-to-end outputs for regression checks (allowing controlled variability where needed)

## Invariant-to-Test Mapping

## Global Invariants

### GI-1: Evidence-First Answering

Tests:

- Unit: `answer_orchestrator` refuses generation when selected bundle is empty
- Integration: API returns structured insufficient-evidence result when retrieval yields no usable candidates
- E2E: out-of-domain query returns limitations/insufficient evidence, not unsupported claims

### GI-2: Multi-Document Default

Tests:

- Unit: scoping resolver marks request as unscoped when no explicit `doc_id`/UI selection is present
- Integration: retrieval adapter is called without `doc_id` filter for unscoped request
- E2E: comparison query returns evidence from multiple `doc_id`s when corpus contains relevant evidence

### GI-3: Deterministic Retrieval and Evidence Assembly

Tests:

- Unit: evidence builder returns identical bundle for identical candidate input and config
- Unit: reranker tie-breaks deterministically
- Integration: repeated runs against fixed retrieval fixtures produce same selected evidence IDs in same order

### GI-4: Traceable Claims

Tests:

- Unit: citation validator rejects missing evidence IDs
- Integration: response validation fails if model cites non-existent ID
- E2E: successful responses contain citations whose IDs all resolve to returned evidence

### GI-5: Modality-Agnostic Evidence Handling

Tests:

- Unit: candidate normalization supports both text and visual candidates
- Integration: bundle builder can include text + visuals in one bundle
- E2E: visual question includes visual evidence when available

## Ingestion and Metadata Invariants

### IM-1: Required Metadata Presence

Tests:

- Unit: metadata validator rejects candidates missing required provenance keys
- Integration: ingestion verification job reports missing metadata fields by item/doc

### IM-2: Metadata Budget Compliance

Tests:

- Unit: metadata serializer enforces key-count and size limits
- Integration: ingestion path logs/rejects oversized metadata payloads

### IM-3: Cross-Doc Joinability

Tests:

- Unit: evidence normalization preserves `doc_id` + asset/chunk identity
- Integration: text and visual evidence items can be traced back to source metadata fields

### IM-4: Stable Document Identity

Tests:

- Integration: scoping by `doc_id` matches ingestion-time identifiers exactly
- E2E: citations expose the same `doc_id` used for retrieval scoping/debug metadata

## Retrieval Invariants

### RI-1: Default Unscoped Retrieval

Tests:

- Unit: request parser/scoping resolver defaults to unscoped
- Integration: retrieval adapter request omits `doc_id` filters for unscoped input

### RI-2: Explicit Scoping Only

Tests:

- Unit: explicit scope recognized only from approved request fields
- Integration: scoped request returns only candidates whose `doc_id` is in requested set
- E2E: scoped query never includes out-of-scope docs in evidence bundle

### RI-3: Retrieval Result Preservation

Tests:

- Unit: candidate mapper preserves rank/score/provenance fields needed downstream
- Integration: evidence builder receives score/rank metadata for reranking

### RI-4: Retrieval-Only Failure Transparency

Tests:

- Integration: zero-candidate path returns retrieval/evidence insufficiency classification
- E2E: logs identify failure stage as retrieval/evidence, not model generation

## Evidence Builder Invariants

### EI-1: Canonical Evidence Normalization

Tests:

- Unit: text and visual candidates map to common evidence schema
- Unit: evidence IDs are unique and stable within a request

### EI-2: Deduplication Correctness

Tests:

- Unit: duplicate text candidates with same `(doc_id, chunk_id)` collapse to one
- Unit: duplicate visual candidates with same `(doc_id, asset_id)` collapse to one
- Integration: dedup runs before final bundle IDs are finalized

### EI-3: Diversity and Dominance Control

Tests:

- Unit: per-doc caps enforce `max 3 text`, `max 2 visuals`
- Unit: unscoped comparison queries prefer multi-doc representation when available
- Integration: scoped queries bypass cross-doc diversity requirements while preserving caps where intended

### EI-4: Bundle Size Bounds

Tests:

- Unit: text/visual total limits enforced
- Unit: global visual cap (`<= 3`) enforced even if per-doc caps would allow more

### EI-5: Deterministic Bundle Selection

Tests:

- Unit: fixed candidate set yields fixed selected bundle and score
- Integration: debug scoring output is present and matches selected result

### EI-6: Provenance Completeness

Tests:

- Unit: returned evidence item serializer always includes required provenance fields
- Integration: API evidence payload for text and visual items contains expected provenance keys

## Reranking Invariants

### RR-1: LLM-Independent Reranking

Tests:

- Unit: reranker module has no model client dependency in constructor/injection
- Integration: reranking executes successfully with model client disabled/mocked out

### RR-2: Stable Signal Computation

Tests:

- Unit: each signal function is deterministic on fixed inputs
- Unit: combined score calculation deterministic and ordered

### RR-3: Cross-Document Support Preference (When Relevant)

Tests:

- Unit: comparison query heuristic boosts bundle with multi-doc support over similar single-doc bundle
- Integration: explicit scoped query does not receive cross-doc boost outside scope

## Model Invocation and Generation Invariants

### MG-1: Evidence-Bounded Prompting

Tests:

- Unit: prompt builder accepts only question + selected evidence + instructions
- Integration: invocation payload excludes non-selected retrieval candidates

### MG-2: Strict Output Contract

Tests:

- Unit: validator rejects malformed JSON
- Unit: validator rejects schema-invalid JSON
- Integration: orchestrator retries (if configured) on malformed output then fails cleanly

### MG-3: Citation Reference Integrity

Tests:

- Unit: validator rejects unknown `citations[].evidence_ids[]`
- Unit: validator rejects unknown `used_evidence_ids[]`
- Integration: API does not return model response with invalid citations

### MG-4: Insufficient Evidence Behavior

Tests:

- Unit: validator accepts schema-valid insufficient-evidence responses
- Integration: orchestrator returns limitations when model indicates insufficiency
- E2E: low-evidence query results in limitations and no fabricated citations

### MG-5: Visual Access Security

Tests:

- Unit: presign helper enforces max TTL
- Integration: visual evidence payload contains short-lived presigned URLs only (no raw private S3 URLs)

## API and Response Invariants

### AR-1: Structured Response Shape

Tests:

- Unit: response serializer always emits required top-level fields
- Integration: successful API responses validate against response schema

### AR-2: Evidence-Response Consistency

Tests:

- Unit: `used_evidence_ids` subset check
- Unit: evidence ID uniqueness check
- Integration: API rejects response objects with citation/evidence mismatch

### AR-3: Scope Transparency

Tests:

- Integration: debug metadata (or equivalent response metadata) indicates scoped vs unscoped mode
- E2E: scoped and unscoped queries produce observable scope markers in logs/telemetry

## Observability Invariants

### OI-1: Stage Attribution

Tests:

- Integration: each failure path emits stage-coded error/event (retrieval, evidence builder, generation, validation)
- E2E: induced failures are attributable to a single stage in logs

### OI-2: Multi-Document Visibility

Tests:

- Integration: telemetry captures count of distinct `doc_id`s in selected bundle
- E2E: comparison query logs `docs_contributing > 1` when appropriate

### OI-3: Citation Error Tracking

Tests:

- Integration: malformed citation responses increment citation validation error metrics with category
- E2E: repeated invalid-citation fixtures produce observable metric/log increments

## MVP Test Suite Layout (Suggested)

- `tests/unit/test_scoping.py`
- `tests/unit/test_candidate_normalization.py`
- `tests/unit/test_deduplication.py`
- `tests/unit/test_bundle_caps.py`
- `tests/unit/test_reranking.py`
- `tests/unit/test_response_schema_validation.py`
- `tests/unit/test_citation_validation.py`
- `tests/integration/test_retrieval_adapter.py`
- `tests/integration/test_evidence_builder_pipeline.py`
- `tests/integration/test_claude_response_validation.py`
- `tests/integration/test_api_query_handler.py`
- `tests/e2e/test_multidoc_queries.py`
- `tests/e2e/test_visual_queries.py`
- `tests/e2e/test_insufficient_evidence.py`

## Execution Plan by Phase

### Phase 0-1 (Contracts + Infra)

- Implement schema validation unit tests first
- Add metadata budget and metadata presence validators
- Add smoke test for environment/config loading

### Phase 2 (Ingestion)

- Add ingestion verification integration tests
- Add seed corpus integrity checks (manifest consistency, `doc_id` uniqueness)

### Phase 3-4 (Retrieval + Evidence Builder)

- Prioritize deterministic unit tests and integration fixtures
- Add regression fixtures for bundle selection outputs

### Phase 5 (Model + Validation)

- Add malformed/invalid model output fixture tests before enabling live model path
- Gate release on citation integrity tests

### Phase 6+ (Eval + Hardening)

- Add scheduled regression runs on golden queries
- Track metric deltas and fail on severe regressions (citation precision/hallucination thresholds)

## Release Gates (Test-Based)

## Gate A: Retrieval/Evidence Ready (before LLM integration)

- All RI/EI unit tests pass
- Deterministic bundle regression tests pass on fixed fixtures
- Multi-doc default and explicit scope tests pass

## Gate B: Grounded Answering Ready

- All MG/AR unit + integration tests pass
- Non-JSON and invalid citation responses are rejected in tests
- End-to-end successful response includes valid citations and evidence provenance

## Gate C: MVP Beta Ready

- E2E suite passes across text, visual, table, and cross-doc categories
- Insufficient-evidence behavior verified
- Observability invariant tests pass (stage attribution + docs contributing metrics)

## Manual Test Checklist (Supplemental)

Use this for early demos and pre-release verification:

- Ask a cross-document comparison question and confirm multiple `doc_id`s contribute
- Ask a visual question and confirm visual evidence appears with presigned URLs
- Ask a scoped question and confirm out-of-scope docs do not appear
- Force malformed model output (mock) and confirm API rejection path
- Ask an unsupported query and confirm limitations/insufficient-evidence response

## Maintenance Rules

- Every new bug fix should add at least one regression test at the lowest effective layer.
- Any change to retrieval defaults, evidence assembly, or response schema must update:
  - `docs/context/SYSTEM_INVARIANTS.md`
  - this test plan
  - corresponding automated tests
