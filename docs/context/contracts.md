# Contracts

This document defines the canonical request/response and evidence contracts for the MVP described in `docs/context/SYSTEM.md`, `docs/context/ARCHITECTURE.md`, and `docs/context/SYSTEM_INVARIANTS.md`.

## Scope

These contracts cover:

- Query request shape (including explicit scoping)
- Model answer JSON shape (strict output contract)
- API query response shape (model answer + evidence payload)
- Canonical evidence item schema
- Metadata requirements and citation integrity rules

## Repository Implementation Status

These contracts are currently implemented as:

- Schemas in `schemas/`
- Validation helpers in `validation/`
- Contract fixtures in `tests/fixtures/`
- Fixture validation tests in `tests/test_contract_fixtures.py`

## Design Rules

- Multi-document is the default behavior unless scope is explicit.
- Retrieval and evidence assembly are deterministic and LLM-independent.
- Model output is strict JSON and validated server-side.
- Citation references must resolve to returned evidence items.

## Canonical Metadata (Indexed Items)

Each indexed item must carry the following metadata (null/omitted only where optional):

- `doc_id` (required)
- `doc_type` (required)
- `asset_type` (required)
- `asset_id` (required for visuals/captions)
- `asset_s3_key` (required for visuals)
- `page` (optional)
- `section` (optional)
- `chunk_id` (required for text chunks)

Constraints:

- Metadata payload must remain within platform limits:
  - size: `<= 1KB`
  - key count: `<= 35`
- Metadata must be sufficient to reconstruct evidence provenance at query time

## Asset Type Vocabulary (MVP)

Canonical `asset_type` values for MVP:

- `text_chunk`
- `caption`
- `figure_image`
- `table_image`
- `diagram`
- `chart_image`
- `embedded_image`

## Query Request Contract

Schema: `schemas/query-request.schema.json`

### Semantics

- If `scope` is omitted, the query is **unscoped** and retrieval must run across all documents.
- If `scope.doc_ids` is present, the query is **scoped** and retrieval must only include those documents.
- `modality_hints` are advisory only; they must not override explicit scoping.

### Example (Unscoped)

```json
{
  "query": "Compare the reported failure rates across the inspection reports and identify any contradictions.",
  "debug": true
}
```

### Example (Scoped)

```json
{
  "query": "What does the table on corrosion thresholds say?",
  "scope": {
    "doc_ids": ["insp-2024-17"],
    "scope_reason": "ui_selection"
  },
  "modality_hints": ["table_image", "text_chunk"]
}
```

## Model Answer Contract (Strict LLM Output)

Schema: `schemas/model-answer.schema.json`

This is the strict JSON the model must return. It intentionally excludes raw evidence objects because those are assembled and validated server-side.

Required top-level fields:

- `answer`
- `citations`
- `used_evidence_ids`
- `limitations`

### Citation Integrity Rules

- Each `citations[].evidence_ids[]` entry must exist in the selected evidence bundle
- Each `used_evidence_ids[]` entry must exist in the selected evidence bundle
- The server validates these rules after model generation

## Evidence Item Contract

Schema: `schemas/evidence-item.schema.json`

Each evidence item must include:

- `evidence_id` (request-local stable identifier like `E1`)
- `doc_id`
- `asset_type`
- `asset_id` or `chunk_id`
- `page` when available

Modality-specific fields:

- Text evidence typically includes `chunk_id` and `snippet`
- Visual evidence typically includes `asset_id`, `asset_s3_key`, and `presigned_url`
- Captions may include `caption` text and can be associated with an `asset_id`

## API Query Response Contract

Schema: `schemas/query-response.schema.json`

The API response extends the model answer contract with:

- `evidence`: returned evidence items for citation resolution and UI display
- `meta` (optional): scope mode, bundle metadata, and debug indicators

This contract is the authoritative payload returned by the query API.

## Validation Sequence (Server-Side)

1. Validate request against `query-request.schema.json`
2. Resolve scope mode (`unscoped` by default)
3. Retrieve candidates and build deterministic evidence bundle
4. Invoke model with selected evidence only
5. Parse and validate model output against `model-answer.schema.json`
6. Validate citation references against selected evidence IDs
7. Build API response and validate against `query-response.schema.json`

## Change Management

If any of the following change, update this document, the JSON schemas, and tests:

- Scoping semantics
- Required response fields
- Evidence item required provenance
- Asset type vocabulary
- Citation validation rules
