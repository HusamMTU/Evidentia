# Evidentia CDK Infrastructure (Phase 1 Foundation)

This document is the infra runbook for the CDK stack in `infra/cdk`.

If this document conflicts with implementation, code wins:

- `infra/cdk/app.py` (context/env wiring)
- `infra/cdk/evidentia_cdk/foundation_stack.py` (actual resources, policies, outputs)

## Canonical Project References

Use these for product/system context instead of duplicating that detail here:

- Product spec: [`docs/context/SYSTEM.md`](../../docs/context/SYSTEM.md)
- Architecture (how/why): [`docs/context/ARCHITECTURE.md`](../../docs/context/ARCHITECTURE.md)
- Hard invariants: [`docs/context/SYSTEM_INVARIANTS.md`](../../docs/context/SYSTEM_INVARIANTS.md)
- Contracts index: [`docs/reference/CONTRACTS.md`](../../docs/reference/CONTRACTS.md)
- Test strategy: [`docs/reference/TEST_STRATEGY.md`](../../docs/reference/TEST_STRATEGY.md)
- Repo map: [`docs/REPO_MAP.md`](../../docs/REPO_MAP.md)

## What This Stack Builds

`EvidentiaFoundation-<stage>` provisions:

- S3 bucket for raw documents
- S3 bucket for extracted visual assets
- S3 Vectors vector bucket + index
- IAM role for Bedrock Knowledge Base ingestion/runtime (`KnowledgeBaseRole`)
- IAM role for API runtime retrieval/model access (`ApiRuntimeRole`)
- Optional Bedrock Knowledge Base + S3 data source (when enabled)
- CloudFormation outputs used by runtime/env sync scripts

## Deployment Modes

- `enableBedrockKb=false` (default): foundation-only deploy (S3, S3 Vectors, IAM)
- `enableBedrockKb=true`: full deploy including Bedrock KB + S3 data source

When `enableBedrockKb=true`, `embeddingModelArn` / `BEDROCK_EMBEDDING_MODEL_ARN` is required.

## Prerequisites

- Python 3.10+
- AWS CLI configured with credentials for target account/region
- CDK CLI (`cdk`)
- `.env` at repo root for environment values

## Build and Deploy (Examples)

Run from `infra/cdk`:

```bash
cd infra/cdk
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
set -a; source ../../.env; set +a

export AWS_REGION=us-east-1
export CDK_DEFAULT_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export CDK_DEFAULT_REGION="$AWS_REGION"

cdk bootstrap "aws://${CDK_DEFAULT_ACCOUNT}/${CDK_DEFAULT_REGION}"
```

Foundation-only deploy:

```bash
cdk synth --app ".venv/bin/python app.py" -c stage=dev -c enableBedrockKb=false
cdk deploy --app ".venv/bin/python app.py" -c stage=dev -c enableBedrockKb=false
```

Full deploy (KB + data source):

```bash
cdk synth --app ".venv/bin/python app.py" -c stage=dev -c enableBedrockKb=true
cdk deploy --app ".venv/bin/python app.py" -c stage=dev -c enableBedrockKb=true
```

Full deploy with explicit embedding/parsing config:

```bash
cdk deploy --app ".venv/bin/python app.py" \
  -c stage=dev \
  -c enableBedrockKb=true \
  -c embeddingModelArn=arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0 \
  -c s3VectorsDataType=float32 \
  -c s3VectorsDimension=1024 \
  -c s3VectorsDistanceMetric=cosine \
  -c advancedParsingStrategy=BEDROCK_DATA_AUTOMATION
```

## CDK Inputs (Context / Env)

Context keys resolve in this order: CDK context (`-c ...`) -> env var -> default.

| Context key | Env var | Default | Notes |
| --- | --- | --- | --- |
| `stage` | `CDK_STAGE` | `dev` | Used in stack naming (`EvidentiaFoundation-<stage>`). |
| `account` | `CDK_DEFAULT_ACCOUNT` | unset | AWS account for stack env. |
| `region` | `CDK_DEFAULT_REGION` | unset | AWS region for stack env. |
| `rawBucketName` | `INFRA_RAW_BUCKET_NAME` | generated | Optional explicit raw bucket name. |
| `assetsBucketName` | `INFRA_ASSETS_BUCKET_NAME` | generated | Optional explicit assets bucket name. |
| `vectorsBucketName` | `INFRA_VECTORS_BUCKET_NAME` | generated | Optional explicit vector bucket name. |
| `apiRuntimePrincipal` | `EVIDENTIA_API_RUNTIME_PRINCIPAL` | `lambda.amazonaws.com` | Assume-role principal for API role. |
| `enableBedrockKb` | `EVIDENTIA_ENABLE_BEDROCK_KB` | `false` | Enables KB + data source resources. |
| `knowledgeBaseName` | `BEDROCK_KNOWLEDGE_BASE_NAME` | derived | Optional explicit KB name. |
| `knowledgeBaseDataSourceName` | `BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_NAME` | derived | Optional explicit data source name. |
| `embeddingModelArn` | `BEDROCK_EMBEDDING_MODEL_ARN` | unset | Required when KB is enabled. |
| `s3VectorsIndexName` | `INFRA_S3_VECTORS_INDEX_NAME` | derived | Optional explicit index name override. |
| `s3VectorsNonFilterableMetadataKeys` | `INFRA_S3_VECTORS_NON_FILTERABLE_METADATA_KEYS` | `AMAZON_BEDROCK_TEXT,AMAZON_BEDROCK_METADATA` | Comma-separated metadata keys. |
| `s3VectorsDataType` | `BEDROCK_S3_VECTORS_DATA_TYPE` | `float32` | S3 Vectors index datatype. |
| `s3VectorsDimension` | `BEDROCK_S3_VECTORS_DIMENSION` | `1024` | Must match embedding model output dimension. |
| `s3VectorsDistanceMetric` | `BEDROCK_S3_VECTORS_DISTANCE_METRIC` | `cosine` | S3 Vectors index distance metric. |
| `advancedParsingStrategy` | `BEDROCK_ADVANCED_PARSING_STRATEGY` | unset | Allowed: `BEDROCK_DATA_AUTOMATION`, `BEDROCK_FOUNDATION_MODEL`. |
| `advancedParsingModelArn` | `BEDROCK_ADVANCED_PARSING_MODEL_ARN` | unset | Required only for `BEDROCK_FOUNDATION_MODEL`. |
| `advancedParsingModality` | `BEDROCK_ADVANCED_PARSING_MODALITY` | unset | For BDA, stack defaults to `MULTIMODAL` when unset. |

Note:

- Deploy-time explicit names use `INFRA_*` env keys.
- Runtime keys in `.env` (`EVIDENTIA_*`, `BEDROCK_*`) should be synced from outputs, not reused as deploy-time naming overrides unless intentional.

## Stack Outputs (Runtime Wiring)

`foundation_stack.py` emits these outputs:

- `StageName`
- `RawBucketName`, `RawBucketArn`
- `AssetsBucketName`, `AssetsBucketArn`
- `VectorsBucketName`, `VectorsBucketArn`
- `S3VectorsIndexName`, `S3VectorsIndexArn`
- `RawPrefixTemplate`, `AssetsPrefixTemplate`
- `KnowledgeBaseRoleArn`, `ApiRuntimeRoleArn`
- `BedrockKnowledgeBaseId`, `BedrockKnowledgeBaseArn` (KB enabled only)
- `BedrockKnowledgeBaseDataSourceId` (KB enabled only)

## Sync `.env` From Stack Outputs

Run from repo root:

```bash
cp .env.example .env   # first time only
./scripts/sync_env_from_stack.sh --region us-east-1 --stack-name EvidentiaFoundation-dev
```

Preview-only mode:

```bash
./scripts/sync_env_from_stack.sh --region us-east-1 --stack-name EvidentiaFoundation-dev --dry-run
```

This sync writes/updates:

- `EVIDENTIA_RAW_BUCKET`
- `EVIDENTIA_ASSETS_BUCKET`
- `EVIDENTIA_VECTORS_BUCKET`
- `EVIDENTIA_API_ROLE_ARN`
- `BEDROCK_KNOWLEDGE_BASE_ID`
- `BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_ID`
- `BEDROCK_S3_VECTORS_INDEX_NAME`

## Smoke Test (Upload + Ingestion)

Run from repo root:

```bash
./scripts/phase1_ingestion_smoke_test.sh \
  --region us-east-1 \
  --stack-name EvidentiaFoundation-dev \
  --file /absolute/path/to/sample.pdf
```

Resolution order in the script:

- `.env` values first (`EVIDENTIA_*`, `BEDROCK_*`)
- fallback to CloudFormation outputs
- optional name-based KB/data source resolution via:
  - `BEDROCK_KNOWLEDGE_BASE_NAME` / `--kb-name`
  - `BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_NAME` / `--data-source-name`
- ingestion manifest persistence (default enabled):
  - upserts `doc_id <-> source_uri` into local SQLite manifest (`.evidentia/ingestion_manifest.db` by default)
  - override path with `--manifest-db` or `EVIDENTIA_INGESTION_MANIFEST_DB`
  - disable for troubleshooting with `--skip-manifest-write`

Extracted asset key notes:

- Bedrock-managed extracted assets are stored under a KB/data-source-scoped prefix, for example:
  - `aws/bedrock/knowledge_bases/<knowledge_base_id>/<data_source_id>/<asset_uuid>.png`
- Because these keys may not include `doc_id`, treat asset key as an opaque locator; keep `doc_id` linkage via ingestion/retrieval provenance metadata.
- The smoke test checks both:
  - legacy/doc-scoped prefix (`documents-assets/<doc_id>/...`) for backward compatibility
  - Bedrock-managed prefix (`aws/bedrock/knowledge_bases/<kb_id>/<data_source_id>/...`)
- For many documents, Bedrock assets can represent a larger page context around a figure/table, not only a tightly cropped object.
- Retrieval normalization should resolve `doc_id` from manifest/provenance metadata, not from asset key shape.

Pass signal:

- ingestion reaches `COMPLETE`
- ingestion stats show indexed/modified documents
- assets prefix check succeeds (count can be zero for text-only PDFs)

## Destroy and Cleanup

Destroy stack (from `infra/cdk`):

```bash
. .venv/bin/activate
set -a; source ../../.env; set +a
cdk destroy "EvidentiaFoundation-dev" --app ".venv/bin/python app.py" --force
```

Storage/vector resources are retained by design (`RETAIN` policies). Use cleanup scripts when you need a fully clean state.

### Cleanup classic S3 leftovers

```bash
# dry-run
./scripts/cleanup_redundant_s3_buckets.sh --region us-east-1 --stack-name EvidentiaFoundation-dev

# execute
./scripts/cleanup_redundant_s3_buckets.sh --region us-east-1 --stack-name EvidentiaFoundation-dev --execute
```

### Cleanup S3 Vectors leftovers

```bash
# dry-run
./scripts/cleanup_redundant_s3vectors.sh --region us-east-1 --stack-name EvidentiaFoundation-dev

# execute (deletes indexes first, then buckets)
./scripts/cleanup_redundant_s3vectors.sh --region us-east-1 --stack-name EvidentiaFoundation-dev --execute
```

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `enable_bedrock_kb=True requires embedding_model_arn` during synth/deploy | KB enabled without embedding model ARN | Set `BEDROCK_EMBEDDING_MODEL_ARN` or pass `-c embeddingModelArn=...`. |
| `advanced_parsing_strategy=BEDROCK_FOUNDATION_MODEL requires advanced_parsing_model_arn` | Missing model ARN for FM parsing | Set `BEDROCK_ADVANCED_PARSING_MODEL_ARN` or `-c advancedParsingModelArn=...`. |
| Smoke test cannot resolve KB/data source IDs | `.env` stale, KB disabled, or wrong stack | Re-sync `.env` from outputs, verify `enableBedrockKb=true`, check stack/region. |
| Smoke test resolves deleted bucket IDs | `.env` points to old resources after redeploy | Re-run `sync_env_from_stack.sh` and retry. |
| `cdk destroy` completes but buckets/vector buckets still exist | Resources are retained intentionally | Run cleanup scripts above if you need full teardown. |
| Deploy fails with resource name collisions | Explicit names pinned to old/stale resources | Remove fixed names (`INFRA_*`, KB/data source name overrides) or clean stale resources first. |

## Fast Redeploy From Clean State

```bash
cd infra/cdk
. .venv/bin/activate
set -a; source ../../.env; set +a

export AWS_REGION=us-east-1
export CDK_DEFAULT_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export CDK_DEFAULT_REGION="$AWS_REGION"

cdk synth --app ".venv/bin/python app.py" -c stage=dev -c enableBedrockKb=true
cdk deploy --app ".venv/bin/python app.py" -c stage=dev -c enableBedrockKb=true
```

Then sync runtime env again:

```bash
./scripts/sync_env_from_stack.sh --region us-east-1 --stack-name EvidentiaFoundation-dev
```
