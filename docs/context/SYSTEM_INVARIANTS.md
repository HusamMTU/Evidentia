# System Invariants

This document defines the non-negotiable rules the system must satisfy at all times. These invariants are implementation-independent and should be enforced through code, tests, and runtime validation.

## Purpose

- Prevent regressions against the core guarantees in `docs/context/SYSTEM.md`
- Keep multi-document behavior first-class
- Make correctness testable across ingestion, retrieval, evidence assembly, and answer generation

## Terminology

- `candidate`: A raw retrieval result from the Knowledge Base
- `evidence item`: A normalized text or visual object used for answer generation
- `evidence bundle`: The selected set of evidence items sent to the model
- `scoped query`: A query explicitly restricted to one or more documents (by `doc_id` or UI selection)

## Global Invariants

### GI-1: Evidence-First Answering

- The system must not generate an answer unless at least one evidence item was retrieved and selected.
- If evidence is insufficient, the system must return a structured insufficient-evidence outcome (not an unsupported answer).

### GI-2: Multi-Document Default

- Retrieval must search across all indexed documents unless the request explicitly scopes document selection.
- Multi-document behavior is the default execution path, not a feature flag or optional mode.

### GI-3: Deterministic Retrieval and Evidence Assembly

- Given the same input query, same scope, same KB state, and same configuration, retrieval and evidence bundle construction must produce the same selected evidence bundle.
- LLM behavior must not affect retrieval or evidence assembly decisions.

### GI-4: Traceable Claims

- Every non-trivial claim in the answer must cite one or more evidence IDs.
- Every cited evidence ID must resolve to a returned evidence item with document identity.

### GI-5: Modality-Agnostic Evidence Handling

- Text and visual evidence are both eligible evidence sources.
- The system must not assume text-only evidence when visual evidence is available and relevant.

## Ingestion and Metadata Invariants

### IM-1: Required Metadata Presence

Each indexed item must carry the canonical metadata fields required by the system contract, with null/omitted values only where explicitly optional.

Required schema keys:

- `doc_id`
- `doc_type`
- `asset_type`
- `asset_id` (for visual/caption assets) or equivalent asset identity where applicable
- `chunk_id` (for text chunks) where applicable
- `asset_s3_key` (visuals only)
- `page` (optional)
- `section` (optional)

### IM-2: Metadata Budget Compliance

- Metadata attached to indexed items must remain within configured platform constraints (size and key-count limits).
- The system must not silently add metadata fields that push items beyond allowed limits.

### IM-3: Cross-Doc Joinability

- Metadata must be sufficient to reconstruct evidence provenance:
  - document identity (`doc_id`)
  - asset/chunk identity
  - storage location for visuals (when present)
- Provenance must survive normalization into evidence items.

### IM-4: Stable Document Identity

- `doc_id` must be unique and stable for the lifetime of an indexed document version.
- Query-time scoping and citation references must use the same `doc_id` semantics used at ingestion.

## Retrieval Invariants

### RI-1: Default Unscoped Retrieval

- Unscoped queries must not pre-filter candidates by `doc_id`.
- Retrieval configuration must not implicitly narrow to a single document unless requested.

### RI-2: Explicit Scoping Only

- `doc_id` filtering is allowed only when scope is explicit in the request (API parameter or UI selection).
- Scoped retrieval must only return candidates from the requested documents.

### RI-3: Retrieval Result Preservation

- Raw retrieval results must preserve ranking/score information needed for deterministic evidence construction and reranking.
- Candidate provenance metadata must not be dropped before evidence normalization.

### RI-4: Retrieval-Only Failure Transparency

- If retrieval returns zero usable candidates, the system must report this as a retrieval/evidence insufficiency outcome, not a generation failure.

## Evidence Builder Invariants

### EI-1: Canonical Evidence Normalization

- All selected evidence must be normalized into a single evidence item schema before model invocation.
- Each evidence item must have a stable evidence ID unique within the request (for example `E1`, `E2`, ...).

### EI-2: Deduplication Correctness

- Text evidence must be deduplicated by `(doc_id, chunk_id)` when `chunk_id` exists.
- Visual evidence must be deduplicated by `(doc_id, asset_id)`.
- Deduplication must happen before final bundle selection and citation ID assignment is finalized.

### EI-3: Diversity and Dominance Control

- Evidence assembly must enforce per-document contribution caps in unscoped mode.
- The bundle must avoid single-document dominance when comparable evidence exists across documents.
- If the query is explicitly scoped to one document, cross-document diversity constraints do not apply.

### EI-4: Bundle Size Bounds

- Final bundles must respect configured text and visual count limits.
- Visual count must never exceed the global visual cap.

### EI-5: Deterministic Bundle Selection

- Bundle scoring and tie-breaking must be deterministic.
- The selected bundle must be explainable from recorded scores/signals (for debugging and evaluation).

### EI-6: Provenance Completeness

Each returned evidence item must include enough provenance for citation and audit:

- `doc_id`
- `asset_type`
- `asset_id` or `chunk_id`
- `page` when available
- snippet/caption/url fields as appropriate to modality

## Reranking Invariants

### RR-1: LLM-Independent Reranking

- Reranking must not call the LLM or depend on model-generated intermediate outputs.

### RR-2: Stable Signal Computation

- Reranking signals (for example rank fusion, modality alignment, evidence density) must be computed from deterministic inputs only.

### RR-3: Cross-Document Support Preference (When Relevant)

- For comparison/aggregation queries, reranking must prefer bundles showing cross-document support when such evidence exists.
- This preference must not override explicit user scoping.

## Model Invocation and Generation Invariants

### MG-1: Evidence-Bounded Prompting

- The model input must include only the selected evidence bundle and the user question (plus system instructions).
- The system must not inject unstated external facts into the generation context.

### MG-2: Strict Output Contract

- The model response must parse as valid JSON matching the response schema.
- Non-JSON or schema-invalid outputs must be rejected and handled explicitly.

### MG-3: Citation Reference Integrity

- Every `citations[].evidence_ids[]` entry must exist in the returned evidence bundle.
- Every `used_evidence_ids[]` entry must exist in the returned evidence bundle.
- Citation validation must occur server-side after model generation.

### MG-4: Insufficient Evidence Behavior

- If the model indicates insufficient evidence, the response must preserve that limitation rather than forcing a definitive answer.
- The system must not fabricate citations to satisfy schema requirements.

### MG-5: Visual Access Security

- Visual evidence URLs passed to the model/client must be presigned with short-lived expiration.
- Asset access must be limited to the minimum required for the request.

## API and Response Invariants

### AR-1: Structured Response Shape

Every successful answer response must include:

- `answer`
- `citations`
- `used_evidence_ids`
- `limitations`

### AR-2: Evidence-Response Consistency

- `used_evidence_ids` must be a subset of the returned evidence item IDs.
- Evidence IDs must be unique within the response.
- Citation statements must not reference evidence omitted from the response payload.

### AR-3: Scope Transparency

- The response (or debug metadata) must allow operators to determine whether the query ran in scoped or unscoped mode.

## Observability Invariants

### OI-1: Stage Attribution

- Each request must emit enough telemetry to attribute failures to one of:
  - ingestion/data quality
  - retrieval
  - evidence builder/reranking
  - model generation
  - output validation

### OI-2: Multi-Document Visibility

- Observability must capture how many distinct documents contributed to the selected evidence bundle.
- This must be measurable per request for regression detection.

### OI-3: Citation Error Tracking

- Citation validation failures must be counted and logged with error category (missing ID, malformed JSON, schema violation, etc.).

## Testable Invariant Checklist (MVP)

These should become automated tests early:

- Unscoped query does not pre-filter by `doc_id`
- Scoped query returns only requested `doc_id`s
- Same input/config/state yields same evidence bundle
- Dedup removes duplicate `(doc_id, chunk_id)` / `(doc_id, asset_id)` items
- Per-document caps are enforced in unscoped mode
- All cited evidence IDs exist in returned evidence
- Non-JSON model output is rejected
- Insufficient-evidence responses are returned without unsupported claims

## Change Control Rule

Any change that modifies retrieval defaults, evidence assembly rules, citation behavior, or output schema must:

- update this file if an invariant changes
- include tests demonstrating the new invariant behavior
- document migration impact on existing evaluations and clients
