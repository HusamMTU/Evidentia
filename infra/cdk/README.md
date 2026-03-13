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
- DynamoDB ingestion manifest table (`doc_id` <-> source URI mapping)
- IAM role for Bedrock Knowledge Base ingestion/runtime (`KnowledgeBaseRole`)
- IAM role for API runtime retrieval/model access (`ApiRuntimeRole`)
- Optional Bedrock Knowledge Base + S3 data source (when enabled)
- CloudFormation outputs used by runtime/env sync scripts

## Deployment Modes

- `enableBedrockKb=false` (default): foundation-only deploy (S3, S3 Vectors, DynamoDB, IAM)
- `enableBedrockKb=true`: full deploy including Bedrock KB + S3 data source

When `enableBedrockKb=true`, `embeddingModelArn` / `BEDROCK_EMBEDDING_MODEL_ARN` is required.

## Prerequisites

- Python 3.10+
- AWS CLI configured with credentials for target account/region
- CDK CLI (`cdk`)
- `.env` at repo root for environment values
- For smoke-test manifest writes, Python `boto3` must be available to `python3` (for example via `pip install -e .` or `uv sync` from repo root)

## Deploy Runbook (Step-by-Step)

This sequence is the easiest reproducible path for a fresh or repeat deploy.

Step 1: Prepare `.env` at repo root

```bash
cd /path/to/repo
cp .env.example .env   # first time only
```

Set/verify deploy-time values in `.env` before deploy:

- `AWS_REGION`
- `BEDROCK_EMBEDDING_MODEL_ARN` (required only when deploying with `enableBedrockKb=true`)

Step 2: Prepare CDK environment (run from `infra/cdk`)

```bash
cd infra/cdk
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
set -a; source ../../.env; set +a
```

Step 3: Export deployment target and bootstrap

```bash
export AWS_REGION="${AWS_REGION:-us-east-1}"
export CDK_DEFAULT_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export CDK_DEFAULT_REGION="$AWS_REGION"

# first time per account/region
cdk bootstrap "aws://${CDK_DEFAULT_ACCOUNT}/${CDK_DEFAULT_REGION}"
```

Step 4: Deploy stack (choose one mode)

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

Step 5: Sync runtime `.env` values from stack outputs (run from repo root)

```bash
cd ../..
./scripts/sync_env_from_stack.sh --region "$AWS_REGION" --stack-name EvidentiaFoundation-dev
```

Preview-only mode:

```bash
./scripts/sync_env_from_stack.sh --region "$AWS_REGION" --stack-name EvidentiaFoundation-dev --dry-run
```

The sync script writes/updates:

- `EVIDENTIA_RAW_BUCKET`
- `EVIDENTIA_ASSETS_BUCKET`
- `EVIDENTIA_VECTORS_BUCKET` (from `VectorsBucketArn`)
- `EVIDENTIA_API_ROLE_ARN`
- `EVIDENTIA_INGESTION_MANIFEST_TABLE_NAME`
- `EVIDENTIA_INGESTION_MANIFEST_SOURCE_URI_INDEX`
- `BEDROCK_KNOWLEDGE_BASE_ID`
- `BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_ID`
- `BEDROCK_S3_VECTORS_INDEX_NAME`

## CDK Inputs and Stack Outputs

Context keys resolve in this order: CDK context (`-c ...`) -> env var -> default.

| Context key | Env var | Default | Notes |
| --- | --- | --- | --- |
| `stage` | `CDK_STAGE` | `dev` | Used in stack naming (`EvidentiaFoundation-<stage>`). |
| `account` | `CDK_DEFAULT_ACCOUNT` | unset | AWS account for stack env. |
| `region` | `CDK_DEFAULT_REGION` | unset | AWS region for stack env. |
| `rawBucketName` | `INFRA_RAW_BUCKET_NAME` | generated | Optional explicit raw bucket name. |
| `assetsBucketName` | `INFRA_ASSETS_BUCKET_NAME` | generated | Optional explicit assets bucket name. |
| `vectorsBucketName` | `INFRA_VECTORS_BUCKET_NAME` | generated | Optional explicit vector bucket name. |
| `ingestionManifestTableName` | `INFRA_INGESTION_MANIFEST_TABLE_NAME` | generated | Optional explicit DynamoDB ingestion manifest table name. |
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

Deploy/runtime note:

- Deploy-time explicit names use `INFRA_*` env keys.
- Runtime keys in `.env` (`EVIDENTIA_*`, `BEDROCK_*`) should be synced from outputs, not reused as deploy-time naming overrides unless intentional.

CloudFormation outputs emitted by `foundation_stack.py`:

| Output key | Availability | Description |
| --- | --- | --- |
| `StageName` | always | Stage value used in stack naming and conventions. |
| `RawBucketName` | always | Raw documents S3 bucket name. |
| `RawBucketArn` | always | Raw documents S3 bucket ARN. |
| `AssetsBucketName` | always | Extracted assets S3 bucket name. |
| `AssetsBucketArn` | always | Extracted assets S3 bucket ARN. |
| `VectorsBucketName` | always | S3 Vectors bucket name. |
| `VectorsBucketArn` | always | S3 Vectors bucket ARN. |
| `S3VectorsIndexName` | always | S3 Vectors index name. |
| `S3VectorsIndexArn` | always | S3 Vectors index ARN. |
| `RawPrefixTemplate` | always | Raw object key template (`documents-raw/{doc_id}/source.pdf`). |
| `AssetsPrefixTemplate` | always | Bedrock-managed assets key template. |
| `IngestionManifestTableName` | always | DynamoDB ingestion manifest table name. |
| `IngestionManifestTableArn` | always | DynamoDB ingestion manifest table ARN. |
| `IngestionManifestSourceUriIndexName` | always | Manifest table GSI name for source URI lookups. |
| `KnowledgeBaseRoleArn` | always | IAM role ARN used by Bedrock KB flows. |
| `ApiRuntimeRoleArn` | always | IAM role ARN used by API/runtime retrieval path. |
| `BedrockKnowledgeBaseId` | `enableBedrockKb=true` | Bedrock KB ID. |
| `BedrockKnowledgeBaseArn` | `enableBedrockKb=true` | Bedrock KB ARN. |
| `BedrockKnowledgeBaseDataSourceId` | `enableBedrockKb=true` | Bedrock KB data source ID. |

## Smoke Test (Upload + Ingestion)

Run from repo root:

```bash
./scripts/phase1_ingestion_smoke_test.sh \
  --region us-east-1 \
  --stack-name EvidentiaFoundation-dev \
  --file /absolute/path/to/sample.pdf
```

This smoke test requires a deployed KB/data source (`enableBedrockKb=true`).

Resolution order in the script:

- `.env` values first (`EVIDENTIA_*`, `BEDROCK_*`)
- fallback to CloudFormation outputs
- optional name-based KB/data source resolution via:
  - `BEDROCK_KNOWLEDGE_BASE_NAME` / `--kb-name`
  - `BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_NAME` / `--data-source-name`
- preflight guard:
  - script aborts when the resolved KB has multiple active data sources
  - bypass only when intentionally testing with `--allow-multiple-data-sources`
- ingestion manifest persistence (default enabled):
  - upserts `doc_id <-> source_uri` into DynamoDB table (`EVIDENTIA_INGESTION_MANIFEST_TABLE_NAME`)
  - status upsert sequence: `uploaded` -> `ingestion_started` -> `ingested`
  - override table name with `--manifest-table-name`
  - override GSI name with `--manifest-source-uri-index-name` (default `source_uri-index`)
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

## Clean Reset and Redeploy

Use this sequence when you want a reproducible clean state and immediate redeploy.

Step 1: Set target stack/region and load env (repo root)

```bash
set -a; source .env; set +a
STACK_NAME="EvidentiaFoundation-dev"
REGION="${AWS_REGION:-us-east-1}"
```

Step 2: (Optional) remove redundant old S3/S3 Vectors resources while stack outputs still exist

```bash
# dry-run
./scripts/cleanup_redundant_s3_buckets.sh --region "$REGION" --stack-name "$STACK_NAME"
./scripts/cleanup_redundant_s3vectors.sh --region "$REGION" --stack-name "$STACK_NAME"

# execute
./scripts/cleanup_redundant_s3_buckets.sh --region "$REGION" --stack-name "$STACK_NAME" --execute
./scripts/cleanup_redundant_s3vectors.sh --region "$REGION" --stack-name "$STACK_NAME" --execute
```

Step 3: Capture retained resource names from stack outputs (needed after destroy)

```bash
RAW_BUCKET="$(aws --region "$REGION" cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`RawBucketName`].OutputValue | [0]' \
  --output text)"
ASSETS_BUCKET="$(aws --region "$REGION" cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`AssetsBucketName`].OutputValue | [0]' \
  --output text)"
VECTORS_BUCKET="$(aws --region "$REGION" cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`VectorsBucketName`].OutputValue | [0]' \
  --output text)"
MANIFEST_TABLE="$(aws --region "$REGION" cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`IngestionManifestTableName`].OutputValue | [0]' \
  --output text)"
```

Step 4: Destroy the stack (from `infra/cdk`)

```bash
cd infra/cdk
. .venv/bin/activate
set -a; source ../../.env; set +a
cdk destroy "$STACK_NAME" --app ".venv/bin/python app.py" --force
cd ../..
```

Step 5: Delete retained resources (S3, S3 Vectors, DynamoDB)

```bash
aws --region "$REGION" s3 rb "s3://$RAW_BUCKET" --force
aws --region "$REGION" s3 rb "s3://$ASSETS_BUCKET" --force

for index_name in $(aws --region "$REGION" s3vectors list-indexes \
  --vector-bucket-name "$VECTORS_BUCKET" \
  --query 'indexes[].indexName' \
  --output text); do
  aws --region "$REGION" s3vectors delete-index \
    --vector-bucket-name "$VECTORS_BUCKET" \
    --index-name "$index_name"
done

until [ "$(aws --region "$REGION" s3vectors list-indexes \
  --vector-bucket-name "$VECTORS_BUCKET" \
  --query 'length(indexes)' \
  --output text)" = "0" ]; do sleep 3; done

aws --region "$REGION" s3vectors delete-vector-bucket --vector-bucket-name "$VECTORS_BUCKET"
aws --region "$REGION" dynamodb delete-table --table-name "$MANIFEST_TABLE"
```

If `aws s3 rb ... --force` fails with `BucketNotEmpty`, the bucket still has versioned objects/delete markers. Remove versions first, then retry bucket deletion.

Step 6: Redeploy full stack and re-sync runtime env

Recommended before redeploy: start from a clean `.env` so stale deploy-time overrides do not leak into the new stack.

```bash
cp .env .env.bak.$(date +%Y%m%d-%H%M%S)
cp .env.example .env
# set at least AWS_REGION and BEDROCK_EMBEDDING_MODEL_ARN (for enableBedrockKb=true)
```

```bash
cd infra/cdk
. .venv/bin/activate
set -a; source ../../.env; set +a

export AWS_REGION="$REGION"
export CDK_DEFAULT_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export CDK_DEFAULT_REGION="$AWS_REGION"

cdk synth --app ".venv/bin/python app.py" -c stage=dev -c enableBedrockKb=true
cdk deploy --app ".venv/bin/python app.py" -c stage=dev -c enableBedrockKb=true
cd ../..

./scripts/sync_env_from_stack.sh --region "$AWS_REGION" --stack-name "$STACK_NAME"
```

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `enable_bedrock_kb=True requires embedding_model_arn` during synth/deploy | KB enabled without embedding model ARN | Set `BEDROCK_EMBEDDING_MODEL_ARN` or pass `-c embeddingModelArn=...`. |
| `advanced_parsing_strategy=BEDROCK_FOUNDATION_MODEL requires advanced_parsing_model_arn` | Missing model ARN for FM parsing | Set `BEDROCK_ADVANCED_PARSING_MODEL_ARN` or `-c advancedParsingModelArn=...`. |
| `ModuleNotFoundError: No module named 'boto3'` during smoke test manifest step | `python3` environment does not include runtime dependencies | Install root deps (`pip install -e .` or `uv sync`) and rerun smoke test. |
| Smoke test cannot resolve KB/data source IDs | `.env` stale, KB disabled, or wrong stack | Re-sync `.env` from outputs, verify `enableBedrockKb=true`, check stack/region. |
| Smoke test fails with "multiple active data sources" | Duplicate data sources exist for the same KB (often from prior dev iterations) | Remove/disable extra data sources and re-sync `.env`; use `--allow-multiple-data-sources` only for deliberate temporary tests. |
| Smoke test cannot resolve ingestion manifest table | `.env` missing table output or stack not updated | Re-run `sync_env_from_stack.sh`, or pass `--manifest-table-name`, or deploy updated stack. |
| Smoke test resolves deleted bucket IDs | `.env` points to old resources after redeploy | Re-run `sync_env_from_stack.sh` and retry. |
| `cdk destroy` completes but buckets/vector buckets/table still exist | Resources are retained intentionally | Run cleanup scripts/commands above if you need full teardown. |
| Deploy fails with resource name collisions | Explicit names pinned to old/stale resources | Remove fixed names (`INFRA_*`, KB/data source name overrides) or clean stale resources first. |
