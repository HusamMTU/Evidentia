# Roadmap (Non-Authoritative)

This roadmap outlines intended sequencing for building the MVP of the multimodal, multi-document grounded QA system.

This file is explicitly **non-authoritative** and may lag implementation.
This document is guidance; if it conflicts with code/contracts/tests, those win.

If this roadmap conflicts with implementation reality, follow:

- Code and infrastructure in `infra/`, `validation/`, and runtime modules
- Schemas in `schemas/`
- Invariants in `docs/context/SYSTEM_INVARIANTS.md`
- Contracts index and validation flow in `docs/reference/CONTRACTS.md`
- Executable checks in `tests/` and `docs/reference/TEST_STRATEGY.md`

## Current Implementation Status (as of 2026-02-27)

- Phase 0 (Contracts and Invariants): **Completed in repo**
  - Schemas: `schemas/query-request.schema.json`, `schemas/model-answer.schema.json`, `schemas/evidence-item.schema.json`, `schemas/query-response.schema.json`
  - Validation layer: `validation/`
  - Contract fixtures and tests: `tests/fixtures/`, `tests/test_contract_fixtures.py`
- Phase 1 (Cloud Foundation and Security): **In progress, foundation deployed**
  - CDK app and stack: `infra/cdk/app.py`, `infra/cdk/evidentia_cdk/foundation_stack.py`
  - Infra docs and runbook: `infra/cdk/README.md`
  - Operational cleanup scripts for repeated deployment attempts:
    - `scripts/cleanup_redundant_s3_buckets.sh` (classic S3)
    - `scripts/cleanup_redundant_s3vectors.sh` (S3 Vectors)
- Phases 2-7: **Not implemented yet**

## Planning Principles

- Build deterministic retrieval and evidence assembly before LLM answering.
- Preserve multi-document behavior as the default from the first implementation.
- Validate contracts early (metadata, evidence objects, output JSON) to avoid rework.
- Ship vertical slices, but with hard gates on evidence and citation correctness.

## MVP Success Criteria

- Users can ask questions across multiple indexed documents by default.
- The system retrieves text and visual evidence (when available) from the KB.
- Answers are generated only from selected evidence.
- Every meaningful claim cites evidence IDs that resolve to concrete document assets/chunks.
- The API returns strict JSON and rejects invalid model outputs.

## Out of Scope (MVP)

- Fine-tuned reranker
- Full knowledge graph
- Advanced contradiction detection
- Automated table normalization

## Assumptions

- AWS account access is available for Bedrock Knowledge Base, S3, and IAM setup.
- Bedrock Knowledge Base advanced parsing is available in the target region.
- Claude vision-capable model is available in the target region.

## Phase 0: Contracts and Invariants (Week 1)

Goal: Freeze the system contracts that all components depend on.

### Tasks

- Define canonical metadata schema for indexed items:
  - `doc_id`, `doc_type`, `asset_type`, `asset_id`, `asset_s3_key`, `page`, `section`, `chunk_id`
- Define evidence item schema used internally and returned to the client.
- Define API request schema:
  - query text
  - optional scoped `doc_id`s / UI-selected documents
  - optional modality hints (future-compatible)
- Define strict response JSON schema:
  - `answer`, `citations`, `used_evidence_ids`, `limitations`
- Define retrieval/evidence invariants:
  - no pre-filter by `doc_id` unless explicitly scoped
  - deterministic evidence assembly
  - dedup keys and per-document caps
- Define citation validation rules:
  - all cited IDs must exist in bundle
  - all `used_evidence_ids` must exist in evidence list

### Deliverables

- `docs/reference/CONTRACTS.md` (contracts index + validation sequence)
- `docs/context/SYSTEM_INVARIANTS.md`
- JSON schemas for request/response (or typed models if codebase is typed)
- Example payloads for text-only and multimodal queries

### Gate (must pass before Phase 1)

- Status: **Passed** (schemas + fixtures + contract validation tests are in repo)
- Team can answer "what is the canonical evidence object?" without ambiguity.
- All metadata fields and constraints are documented (including size/key count limits).

## Phase 1: Cloud Foundation and Security (Week 1-2)

Goal: Provision the minimum AWS infrastructure required for ingestion and querying.

### Tasks

- Create S3 bucket/prefix layout:
  - `documents-raw/{doc_id}/source.pdf`
  - `aws/bedrock/knowledge_bases/{knowledge_base_id}/{data_source_id}/{asset_uuid}.png` (Bedrock-managed extracted assets)
- Create/Configure Bedrock Knowledge Base:
  - multimodal KB over unstructured docs
  - advanced parsing enabled
  - vector store = S3 Vectors
- Define IAM roles and permissions:
  - KB role: read raw docs, write assets, write vectors
  - API role: retrieve from KB, read assets for presigning, invoke Claude
- Implement presigned URL generation policy (short expiry)
- Document environment config:
  - region, bucket names, KB ID, model ID, timeouts

### Deliverables

- Infrastructure definitions (IaC preferred: Terraform/CDK/CloudFormation)
- IAM policy docs or source
- Environment configuration template (`.env.example` or equivalent)

### Gate

- Test document can be placed in `documents-raw/`.
- KB can ingest from configured source without permission failures.
- Asset bucket paths are writable by KB and readable by API role (via presign flow).

## Phase 2: Ingestion Pipeline MVP (Week 2)

Goal: Make document ingestion reproducible and verify metadata quality.

### Tasks

- Implement document registration flow:
  - generate/accept `doc_id`
  - assign `doc_type`
  - upload source PDF to raw path
- Trigger KB sync/ingestion (manual endpoint or script is fine for MVP)
- Build ingestion verification checks:
  - chunks exist
  - visual assets extracted when present
  - metadata fields populated and joinable
  - doc provenance mapping captured (`doc_id` <-> raw source URI/object key); do not derive `doc_id` from extracted asset key paths
- Create a seed corpus (8-20 docs) covering:
  - text-heavy
  - table-heavy
  - figure/diagram-heavy
  - mixed-media
  - at least a few docs with overlapping topics for cross-doc QA

### Deliverables

- Ingestion script/service endpoint
- Seed dataset manifest (`doc_id`, `doc_type`, source path)
- Ingestion verification report (simple JSON/CSV/log output is fine)

### Gate

- At least 5 mixed documents successfully ingest end-to-end.
- Retrieved KB items include required metadata fields for both text and visual evidence.

## Phase 3: Retrieval API (Deterministic, No LLM Yet) (Week 2-3)

Goal: Expose a query endpoint that performs multi-document retrieval by default.

### Tasks

- Implement `POST /query` (or equivalent internal handler) for query intake.
- Integrate KB retrieval with default behavior:
  - retrieve across all documents
  - no `doc_id` filter unless explicitly scoped
- Add scoped retrieval mode:
  - explicit `doc_id` in request
  - UI-selected docs (if UI exists)
- Implement retrieval logging:
  - number of results
  - doc distribution
  - modality distribution (if detectable)
- Return debug mode payloads (MVP-friendly):
  - raw candidates
  - metadata
  - retrieval scores/ranks

### Deliverables

- Query API endpoint (retrieval-only mode)
- Unit tests for scoping behavior
- Example requests/responses for multi-doc and scoped queries

### Gate

- Same query returns candidates from multiple `doc_id`s when relevant.
- Scoped query filters correctly to requested docs only.
- Retrieval behavior is deterministic for identical inputs/config.

## Phase 4: Evidence Builder and Bundle Reranking (Week 3-4)

Goal: Convert raw retrieval candidates into a high-quality cross-document evidence bundle.

### Tasks

- Implement candidate normalization:
  - map KB outputs into internal evidence item schema
  - assign stable evidence IDs (`E1`, `E2`, ...)
- Implement deduplication:
  - `(doc_id, asset_id)` for visuals (`doc_id` sourced from metadata/provenance, not parsed from `asset_s3_key`)
  - `(doc_id, chunk_id)` for text
- Implement bundle construction rules:
  - text snippets: target 2-8
  - visuals: target 0-3
  - include captions when present
  - enforce per-document caps (max 3 text, max 2 visuals, max 3 visuals total)
- Implement bundle types:
  - text-only
  - visual-led
  - table-led
  - cross-document comparison
- Implement reranking signals (heuristic MVP):
  - reciprocal rank fusion
  - modality alignment
  - explicit numeric/reference cues
  - evidence density
  - cross-document agreement/support boost
- Select top bundle deterministically

### Deliverables

- `EvidenceBuilder` module/service
- Reranking module with deterministic scoring output
- Debug endpoint or logs showing why a bundle was selected

### Gate

- Bundle assembly is deterministic and reproducible.
- Per-document dominance caps are enforced.
- Comparison-style queries produce bundles with multiple `doc_id`s when evidence exists.

## Phase 5: Claude Vision Answer Generation + Validation (Week 4)

Goal: Add grounded answer generation on top of the deterministic evidence pipeline.

### Tasks

- Build Claude invocation payload with:
  - question
  - evidence list (text snippets + image URLs)
  - strict instructions (evidence-only, cite evidence IDs, JSON-only)
- Generate presigned URLs for visual assets with short TTL
- Implement response validation:
  - strict JSON parse
  - schema validation
  - cited IDs exist in evidence bundle
  - `used_evidence_ids` subset of evidence bundle
- Implement failure handling:
  - retry on malformed JSON (limited retries)
  - return structured error when validation fails repeatedly
- Add insufficient-evidence behavior:
  - model instructed to state limitations
  - API returns limitations even when answer confidence is low

### Deliverables

- Claude invocation service
- Validation layer (schema + citation integrity checks)
- End-to-end query path returning answer + evidence

### Gate

- API rejects non-JSON model outputs.
- Citation references are always resolvable to evidence items.
- System can return "insufficient evidence" instead of hallucinating unsupported claims.

## Phase 6: Evaluation Harness and Observability (Week 4-5)

Goal: Measure whether the system is meeting the core guarantees.

### Tasks

- Build evaluation set with labeled queries:
  - text-only
  - visual interpretation
  - table reasoning
  - cross-document comparison
  - contradiction detection (basic)
  - citation correctness
- Implement metrics:
  - Evidence Recall@K
  - citation precision
  - cross-document synthesis accuracy
  - hallucination rate
- Add runtime observability:
  - retrieval coverage per doc
  - number of contributing docs
  - bundle size
  - citation precision errors
  - insufficient evidence responses
- Add structured logs for each stage:
  - retrieval
  - evidence builder
  - answer generation
  - validation

### Deliverables

- Eval harness/scripts
- Baseline metrics report
- Dashboard/log queries (or documented metrics export)

### Gate

- Metrics can be computed repeatably from stored runs.
- Observability is sufficient to diagnose bad answers into retrieval vs bundling vs generation failures.

## Phase 7: Hardening and Beta Readiness (Week 5-6)

Goal: Stabilize the MVP for internal users.

### Tasks

- Add rate limits / request timeouts / circuit breakers
- Improve prompt and validation ergonomics without changing system guarantees
- Add regression test suite for:
  - scoping behavior
  - citation integrity
  - multi-document diversity caps
  - malformed model response handling
- Add basic audit trail per request:
  - query
  - selected evidence IDs
  - cited evidence IDs
  - validation outcome
- Document operational runbooks:
  - ingestion troubleshooting
  - KB sync issues
  - model output validation failures

### Deliverables

- Beta-ready service deployment
- Regression test suite
- Runbook documentation

### Gate

- Stable end-to-end demos across all evaluation categories.
- No known violations of evidence-first or citation integrity invariants.

## Workstreams That Can Run in Parallel

- Contracts/validation schema work can begin before infrastructure is complete.
- IaC/security setup can proceed in parallel with API scaffolding.
- Evaluation dataset authoring can start during ingestion work (using seed corpus).
- Observability instrumentation should be added incrementally during Phases 3-5, not deferred.

## Suggested Team Split (if applicable)

- Platform/Infra: Phase 1 + ingestion plumbing
- Backend/Core Retrieval: Phases 3-4
- LLM/Validation: Phase 5
- QA/Eval: Phase 6 (starting earlier with dataset prep)

## First Two Weeks (Concrete Execution Checklist)

### Week 1

- Freeze contracts and invariants
- Stand up S3 buckets/prefixes
- Configure Bedrock KB + S3 Vectors + advanced parsing
- Define IAM roles and test permissions

### Week 2

- Build ingestion script/endpoint and seed corpus ingestion
- Verify metadata completeness and asset extraction
- Implement retrieval-only query API with multi-doc default and scoped mode

## Exit Criteria for MVP

- End-to-end query flow works on a mixed corpus.
- Multi-document retrieval is the default behavior.
- Evidence builder outputs deterministic bundles with diversity caps.
- Claude responses are grounded, strict-JSON, and citation-valid.
- Evaluation metrics and observability are in place to track regressions.
