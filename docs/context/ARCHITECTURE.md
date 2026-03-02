# Architecture Overview

This document is the canonical architecture reference. It explains how the system works and why the design is structured this way.

## Architectural Intent

- Preserve multi-document behavior as the default execution path.
- Keep retrieval/evidence assembly deterministic and inspectable.
- Isolate generation from retrieval decisions.
- Enforce grounded outputs through post-generation validation.

## Core Components

- Ingestion surface (document registration/upload)
- Raw document storage (S3 raw prefix)
- Ingestion manifest/provenance store (DynamoDB; `doc_id` <-> source URI mapping)
- Knowledge base ingestion/parsing (Bedrock KB + advanced parsing)
- Vector retrieval backend (S3 Vectors)
- Retrieval adapter
- Evidence builder + reranker
- Model invocation orchestrator
- Output validation layer
- API response assembly layer
- Observability/telemetry layer

## End-to-End Flow

### Ingestion Path

1. Documents are stored in raw storage.
2. Ingestion manifest persists the stable `doc_id` to source URI mapping at registration/upload time.
3. Knowledge base ingestion parses and chunks content.
4. Visual artifacts are extracted to asset storage.
5. Text and visual representations are embedded and indexed.
6. Ingestion manifest status is updated across ingestion lifecycle states (for example `uploaded` -> `ingestion_started` -> `ingested`).
7. Metadata is preserved for downstream provenance.

Why:

- Separates source-of-record content from derived artifacts.
- Enables multimodal retrieval and citation traceability.
- Keeps ingestion reproducible and diagnosable.
- Keeps `doc_id` semantics stable even when extracted asset key paths do not include `doc_id`.

### Query Path

1. API receives the user query.
2. Scope resolver determines scoped vs unscoped execution.
3. Retrieval adapter pulls candidates from the KB/vector backend.
4. Candidate provenance is normalized and `doc_id` is resolved from manifest-backed source metadata.
5. Evidence builder normalizes, deduplicates, and reranks candidates.
6. Selected evidence is passed to the model orchestrator.
7. Model output is validated and cross-checked against evidence IDs.
8. Final response is assembled and returned with evidence payload.

Why:

- Retrieval/evidence selection remains deterministic and testable.
- Model is constrained to selected evidence rather than raw corpus state.
- Validation catches schema/citation drift before response delivery.
- Provenance join does not depend on parsing storage key naming conventions.

## Determinism Boundaries

Deterministic stages:

- Scope resolution
- Retrieval request construction
- Evidence normalization/deduplication/reranking
- Response validation and citation integrity checks

Non-deterministic stage:

- LLM text generation

Design control:

- Non-deterministic generation is bounded by deterministic evidence and strict validation.

## Security Architecture

- Principle of least privilege between KB role and API runtime role.
- Short-lived presigned URLs for visual asset access.
- Separation of raw storage, derived assets, and vector resources.
- Validation and logging designed to avoid leaking sensitive raw context.

## Observability Architecture

The system emits telemetry at stage boundaries to support attribution of failures to:

- ingestion/data quality
- retrieval
- evidence builder/reranking
- model generation
- output validation

It also tracks multi-document participation and citation quality signals for regression detection.

## Evolution Constraints

Architecture changes must preserve:

- Multi-document default behavior
- Deterministic retrieval/evidence assembly
- Evidence-bounded generation
- Strong citation traceability
- Server-side validation gates before response return

## Related References

- Product goals/non-goals: `docs/context/SYSTEM.md`
- Hard invariants: `docs/context/SYSTEM_INVARIANTS.md`
- Canonical shapes: `schemas/*.schema.json`
- Contracts index + validation sequence: `docs/reference/CONTRACTS.md`
- Test strategy: `docs/reference/TEST_STRATEGY.md`
