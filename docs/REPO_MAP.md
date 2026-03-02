# Repository Map

One-page map of where core concepts live.

## Documentation

- `docs/AGENT.md`: entrypoint for contributors/agents
- `docs/context/SYSTEM.md`: product spec (goals/non-goals/high-level guarantees)
- `docs/context/ARCHITECTURE.md`: canonical architecture (how + why)
- `docs/context/SYSTEM_INVARIANTS.md`: hard laws with enforcement pointers
- `docs/reference/CONTRACTS.md`: contracts index + validation sequence
- `docs/reference/TEST_STRATEGY.md`: invariant coverage strategy and mapping
- `docs/plans/ROADMAP.md`: non-authoritative sequencing guidance

## Canonical Runtime Contracts

- `schemas/`
  - `query-request.schema.json`
  - `model-answer.schema.json`
  - `evidence-item.schema.json`
  - `query-response.schema.json`

## Validation Layer

- `validation/validators.py`: schema validation + citation integrity checks
- `validation/schema_loader.py`: schema loading and resolution support
- `validation/errors.py`: validation error types

## Tests and Fixtures

- `tests/test_contract_fixtures.py`: executable contract fixture checks
- `tests/fixtures/`: valid payload/evidence fixtures used by contract tests
- `tests/`: location for unit/integration/e2e suites

## Infrastructure

- `infra/cdk/app.py`: CDK app entrypoint and context/env wiring
- `infra/cdk/evidentia_cdk/foundation_stack.py`: foundation resources (S3, S3 Vectors, IAM, optional Bedrock KB)
- `infra/cdk/README.md`: infra deployment/operations runbook

## Operational Scripts

- `scripts/phase1_ingestion_smoke_test.sh`: ingestion smoke validation
- `scripts/sync_env_from_stack.sh`: populate env from stack outputs
- `scripts/cleanup_redundant_s3_buckets.sh`: cleanup classic S3 leftovers
- `scripts/cleanup_redundant_s3vectors.sh`: cleanup S3 Vectors leftovers

## Data and Assets

- `assets/`: local static assets used by the project
- `documents-raw/*`, `documents-assets/*`: storage paths described in infra docs (runtime in AWS)

## Change Reminders

- API shape changes: update `schemas/`, `validation/`, `tests/`, and `docs/reference/CONTRACTS.md`.
- Invariant behavior changes: update `docs/context/SYSTEM_INVARIANTS.md` and `docs/reference/TEST_STRATEGY.md`.
- Pipeline stage changes: update `docs/context/ARCHITECTURE.md` flow and this file.
