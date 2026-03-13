<div align="center">
  <h1>Evidentia</h1>
  <p><strong>Grounded Multimodal Document Intelligence</strong></p>
  <p>AWS foundation stack · provenance join layer · validation contracts · S3 Vectors inspection</p>
</div>

Evidentia is a multimodal grounded document intelligence system. This repo currently focuses on the AWS foundation stack, provenance join layer, validation contracts, and a read-only S3 Vectors inspector used to debug Bedrock Knowledge Base ingestion and retrieval behavior.

## What's In This Repo

- `infra/cdk`: foundation AWS infrastructure and optional Bedrock Knowledge Base wiring
- `provenance`: canonical `doc_id <-> source_uri` join layer
- `validation`: request, model-output, and citation validation
- `tools/s3_vectors_inspector`: read-only web UI for inspecting vectors, metadata, and similarity
- `scripts`: env sync, smoke tests, cleanup, and helper scripts

## Current Status

- This is a foundation-stage repo, not a finished end-user product.
- The strongest areas today are infrastructure, provenance wiring, contract validation, and operational inspection tooling.
- Retrieval, evidence assembly, and API orchestration are documented architecturally, but not all planned runtime components exist yet.
- Some docs describe target behavior and invariants beyond the current implementation. When docs conflict with code, code and executable tests win.

## Quick Start

1. Install dependencies from the repo root.

```bash
uv sync
```

2. Create the env file.

```bash
cp .env.example .env
```

3. Deploy infrastructure.

Use the step-by-step infra runbook:

- [infra/cdk/README.md](infra/cdk/README.md)

4. Sync runtime env values from the deployed stack.

```bash
./scripts/sync_env_from_stack.sh --region us-east-1 --stack-name EvidentiaFoundation-dev
```

5. Run the ingestion smoke test with a real document.

```bash
./scripts/phase1_ingestion_smoke_test.sh \
  --region us-east-1 \
  --stack-name EvidentiaFoundation-dev \
  --file /absolute/path/to/sample.pdf
```

6. Run the S3 Vectors inspector.

```bash
./scripts/run_s3_vectors_inspector.sh --port 8787
```

Then open `http://127.0.0.1:8787`.

## Typical Workflows

| Goal | Start Here |
| --- | --- |
| Deploy infrastructure | [infra/cdk/README.md](infra/cdk/README.md) |
| Clean reset and redeploy | [infra/cdk/README.md](infra/cdk/README.md) |
| Understand provenance mapping | [provenance/README.md](provenance/README.md) |
| Run contract validation | [validation/README.md](validation/README.md) |
| Inspect vectors and similarity behavior | [tools/s3_vectors_inspector/README.md](tools/s3_vectors_inspector/README.md) |

## Repo Map

| Path | Purpose |
| --- | --- |
| `infra/cdk` | AWS CDK stack and deployment runbook |
| `provenance` | manifest-backed provenance resolution |
| `validation` | schema and citation integrity validation |
| `tools/s3_vectors_inspector` | read-only vector inspection UI |
| `scripts` | deployment, sync, smoke, and cleanup helpers |
| `schemas` | canonical JSON schemas |
| `docs/context` | system, architecture, and invariants |
| `docs/reference` | contracts and test strategy |
| `tests` | contract, provenance, and inspector tests |

## Core Concepts

| Term | Meaning |
| --- | --- |
| `doc_id` | Stable repo-level document identifier |
| `source_uri` | Raw source object URI for a document |
| ingestion manifest | Canonical join layer between `doc_id` and `source_uri` |
| vector bucket | Amazon S3 Vectors container |
| index | Query target inside a vector bucket |
| Bedrock data source | Bedrock Knowledge Base ingestion source config, not a raw document ID |

## Key Invariants

These are the most operationally important rules for working in this repo:

- `doc_id` must come from provenance metadata and manifest resolution, not from parsing Bedrock-managed asset key paths.
- Retrieval is multi-document by default unless the request is explicitly scoped.
- No non-trivial answer claim should survive without resolvable evidence IDs.
- Text and visual evidence are both first-class inputs.
- Retrieval and evidence assembly are intended to be deterministic for the same input, state, and config.

Full invariant registry:

- [docs/context/SYSTEM_INVARIANTS.md](docs/context/SYSTEM_INVARIANTS.md)

## Development Notes

- Python: `>=3.10`
- Root package metadata: [pyproject.toml](pyproject.toml)
- Install with `uv sync` or `pip install -e .`
- Main currently useful test entry points:

```bash
python3 -m unittest tests/test_contract_fixtures.py
python3 -m unittest tests/test_ingestion_manifest_store.py
python3 -m unittest tests/test_retrieval_provenance_normalizer.py
python3 -m unittest tests/test_s3_vectors_inspector.py
```

## Detailed Docs

- [System Product Spec](docs/context/SYSTEM.md)
- [Architecture Overview](docs/context/ARCHITECTURE.md)
- [System Invariants](docs/context/SYSTEM_INVARIANTS.md)
- [Contracts Index](docs/reference/CONTRACTS.md)
- [Test Strategy](docs/reference/TEST_STRATEGY.md)
- [Repository Map](docs/REPO_MAP.md)
