# Contracts Index (Reference, Non-Authoritative)

This document is guidance; if it conflicts with code/contracts/tests, those win.

This file is a **contracts index + validation sequence**. It does not define canonical payload shapes.

Canonical shapes live only in `schemas/`.

## Source of Truth

- Canonical schema definitions: `schemas/*.schema.json`
- Runtime validation logic: `validation/validators.py`
- Contract fixture checks: `tests/test_contract_fixtures.py`
- Provenance join logic: `provenance/manifest_store.py` (DynamoDB-backed), `provenance/retrieval_normalizer.py`

## Schema Index

| Contract Area | Canonical Schema File | Notes |
| --- | --- | --- |
| Query request | `schemas/query-request.schema.json` | Input payload shape, scoping fields, modality hints, debug/request metadata. |
| Model answer | `schemas/model-answer.schema.json` | Strict LLM JSON output shape before server enrichment. |
| Evidence item | `schemas/evidence-item.schema.json` | Normalized evidence object used in API response and citation resolution. |
| Query response | `schemas/query-response.schema.json` | Final API payload shape (model answer + evidence + optional meta). |

## Provenance Join Rule

- Treat `evidence.asset_s3_key` as an opaque storage locator (do not parse business IDs from key shape).
- `doc_id` must come from ingestion/retrieval provenance metadata and remain stable end-to-end.
- For Bedrock-managed assets, key paths can omit `doc_id` (for example `aws/bedrock/knowledge_bases/<kb>/<ds>/<uuid>.png`); join logic must not depend on doc-id-in-path conventions.

## Validation Entry Points

Implemented in `validation/validators.py`:

- `validate_query_request(payload)`
- `validate_model_answer(payload)`
- `validate_evidence_item(payload)`
- `validate_query_response(payload)`
- `validate_citation_integrity(model_answer, evidence_items)`
- `validate_model_answer_against_evidence(model_answer, evidence_items)`

## Server-Side Validation Sequence

Recommended sequence for query handling:

1. Validate request payload with `validate_query_request`.
2. Resolve request mode (scoped/unscoped) from request fields.
3. Retrieve candidates from KB/vector backend.
4. Normalize retrieval provenance and resolve stable `doc_id` using ingestion manifest mapping (`normalize_retrieval_candidate_doc_id`).
5. Build deterministic evidence bundle.
6. Validate model JSON shape with `validate_model_answer`.
7. Validate citation integrity against selected evidence IDs with `validate_citation_integrity` (or `validate_model_answer_against_evidence`).
8. Build final API response and validate with `validate_query_response`.

## Change Workflow

When contract behavior changes:

1. Update schema files in `schemas/` first.
2. Update runtime validators in `validation/` if behavior changes beyond schema validation.
3. Update fixtures/tests in `tests/fixtures/` and `tests/test_contract_fixtures.py`.
4. Update this index document only to reflect file locations, validation flow, or references.
