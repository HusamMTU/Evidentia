# Evidentia CDK (Phase 1 Foundation)

This CDK app provisions the Phase 1 AWS foundation for the Evidentia MVP:

- S3 buckets for raw documents and extracted visual assets
- S3 Vector Bucket + Vector Index for S3 Vectors storage (KB vector store backend)
- IAM role for Bedrock Knowledge Base access (raw docs + assets paths)
- IAM role for API runtime access (asset reads/presigning + Bedrock invoke/retrieve)
- Stack outputs for runtime configuration wiring
- Optional Bedrock Knowledge Base + S3 data source resources (context-driven)

## Bedrock KB Support Status

This stack now supports optional provisioning of:

- Bedrock Knowledge Base (`VECTOR`)
- S3 Vectors storage configuration (`S3_VECTORS`)
- Bedrock S3 data source (`S3`)

The resources are disabled by default and enabled via CDK context/environment because they require environment-specific values (for example an embedding model ARN and S3 Vectors index name).

## Architecture Flow

```mermaid
flowchart LR
  subgraph Ingestion["Ingestion Path"]
    DOCS["Source PDFs"] --> RAW["Raw Documents Bucket<br/>documents-raw/{doc_id}/source.pdf"]
    RAW -->|S3 data source| DS["Bedrock Data Source<br/>(optional)"]
    DS --> KB["Bedrock Knowledge Base<br/>(optional)"]
    KB -->|Vector storage| VECT["S3 Vector Bucket + Index"]
    KB -->|Extracted visuals| ASSETS["Assets Bucket<br/>documents-assets/{doc_id}/{asset_id}.png"]
  end

  subgraph Query["Query Path"]
    API["API Runtime<br/>(Lambda/ECS/etc.)"] -->|Retrieve / RetrieveAndGenerate| KB
    API -->|Read + presign URLs| ASSETS
    API -->|Invoke model| MODEL["Bedrock Model<br/>(Claude, etc.)"]
    MODEL --> RESP["Answer + Citations"]
  end

  KBROLE["IAM Role: KnowledgeBaseRole"] -.assumed by.-> KB
  APIR["IAM Role: ApiRuntimeRole"] -.assumed by.-> API
```

## Quick Start

1. Create a virtual environment for the CDK app
2. Install dependencies
3. Bootstrap CDK (once per account/region)
4. Synthesize (recommended)
5. Deploy the stack

Example:

```bash
cd infra/cdk
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cdk bootstrap
cdk synth --app ".venv/bin/python app.py"
cdk deploy --app ".venv/bin/python app.py"
```

## Deploy Commands (Tailored Flow)

Use explicit account/region on bootstrap to avoid deploying to the wrong default environment:

```bash
cd infra/cdk
. .venv/bin/activate
set -a; source ../../.env; set +a

export AWS_REGION=us-east-1
export CDK_DEFAULT_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export CDK_DEFAULT_REGION="$AWS_REGION"

cdk bootstrap "aws://${CDK_DEFAULT_ACCOUNT}/${CDK_DEFAULT_REGION}"
cdk synth --app ".venv/bin/python app.py" -c stage=dev
cdk deploy --app ".venv/bin/python app.py" -c stage=dev
```

Populate `.env.example` values from CloudFormation outputs after deploy (bucket names, role ARNs).

## Destroy Stack

From `infra/cdk`:

```bash
. .venv/bin/activate
set -a; source ../../.env; set +a

cdk destroy "EvidentiaFoundation-dev" --app ".venv/bin/python app.py" --force
```

For a non-`dev` stage, replace the stack name with `EvidentiaFoundation-<stage>`.

Important:

- The stack uses `RETAIN` policies for storage resources, so destroy may leave S3/S3 Vectors resources behind by design.
- Use the cleanup scripts in this README when you need to remove retained buckets/vector buckets after stack destroy.

If your `.env` file uses plain `KEY=value` lines (no `export` prefix), use:

```bash
set -a; source ../../.env; set +a
```

If your `.env` already uses `export KEY=value`, plain sourcing is enough:

```bash
source ../../.env
```

## Context Values

Optional CDK context values are shown below. Each value can also be provided via environment variable (as implemented in `infra/cdk/app.py`).

| Context key | Env var | Meaning | Default | Required |
| --- | --- | --- | --- | --- |
| `stage` | `CDK_STAGE` | Environment/stage label used in stack naming and default KB/data source names. | `dev` | No |
| `account` | `CDK_DEFAULT_ACCOUNT` | Target AWS account for stack environment. | AWS CLI default | No |
| `region` | `CDK_DEFAULT_REGION` | Target AWS region for stack environment. | AWS CLI/default env | No |
| `apiRuntimePrincipal` | `EVIDENTIA_API_RUNTIME_PRINCIPAL` | IAM service principal allowed to assume the API runtime role. | `lambda.amazonaws.com` | No |
| `rawBucketName` | `INFRA_RAW_BUCKET_NAME` | Explicit S3 bucket name for raw input documents. If omitted, CloudFormation generates one. | CloudFormation-generated | No |
| `assetsBucketName` | `INFRA_ASSETS_BUCKET_NAME` | Explicit S3 bucket name for extracted visual assets. If omitted, CloudFormation generates one. | CloudFormation-generated | No |
| `vectorsBucketName` | `INFRA_VECTORS_BUCKET_NAME` | Explicit **S3 Vector Bucket** name (`AWS::S3Vectors::VectorBucket`). If omitted, CloudFormation generates one. | CloudFormation-generated | No |
| `enableBedrockKb` | `EVIDENTIA_ENABLE_BEDROCK_KB` | Toggles creation of Bedrock Knowledge Base and S3 data source resources. | `false` | No |
| `knowledgeBaseName` | `BEDROCK_KNOWLEDGE_BASE_NAME` | Name for the Bedrock Knowledge Base resource. | `evidentia-kb-{stage}` | No |
| `knowledgeBaseDataSourceName` | `BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_NAME` | Name for the Bedrock S3 data source attached to the KB. | `evidentia-raw-s3-{stage}` | No |
| `embeddingModelArn` | `BEDROCK_EMBEDDING_MODEL_ARN` | ARN of the embedding model used by the vector KB configuration. | None | Yes, if `enableBedrockKb=true` |
| `s3VectorsIndexName` | `BEDROCK_S3_VECTORS_INDEX_NAME` | Name of the S3 Vectors index resource. If omitted, stack uses `evidentia-{stage}-index`. | `evidentia-{stage}-index` | No |
| `s3VectorsDataType` | `BEDROCK_S3_VECTORS_DATA_TYPE` | Vector data type for the S3 Vectors index. | `float32` | No |
| `s3VectorsDimension` | `BEDROCK_S3_VECTORS_DIMENSION` | Embedding vector dimension for the S3 Vectors index (must match embedding model output dimension). | `1024` | No |
| `s3VectorsDistanceMetric` | `BEDROCK_S3_VECTORS_DISTANCE_METRIC` | Similarity metric for the S3 Vectors index. | `cosine` | No |
| `advancedParsingStrategy` | `BEDROCK_ADVANCED_PARSING_STRATEGY` | Optional advanced parsing mode for ingestion. Allowed: `BEDROCK_DATA_AUTOMATION`, `BEDROCK_FOUNDATION_MODEL`. | unset (disabled) | No |
| `advancedParsingModelArn` | `BEDROCK_ADVANCED_PARSING_MODEL_ARN` | ARN of parsing model used only when `advancedParsingStrategy=BEDROCK_FOUNDATION_MODEL`. | None | Conditional |
| `advancedParsingModality` | `BEDROCK_ADVANCED_PARSING_MODALITY` | Optional modality hint passed to advanced parsing configuration. For `BEDROCK_DATA_AUTOMATION`, the stack defaults to `MULTIMODAL` when unset. | unset (`MULTIMODAL` applied for BDA) | No |

Example:

```bash
cdk deploy --app ".venv/bin/python app.py" \
  -c stage=dev \
  -c apiRuntimePrincipal=lambda.amazonaws.com
```

Example with KB + S3 data source enabled:

```bash
cdk deploy --app ".venv/bin/python app.py" \
  -c stage=dev \
  -c enableBedrockKb=true \
  -c embeddingModelArn=arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0 \
  -c s3VectorsIndexName=evidentia-dev-index \
  -c s3VectorsDataType=float32 \
  -c s3VectorsDimension=1024 \
  -c s3VectorsDistanceMetric=cosine \
  -c advancedParsingStrategy=BEDROCK_DATA_AUTOMATION
```

Important:

- Deploy-time explicit bucket names are read from context keys or `INFRA_*` environment variables.
- Runtime output values such as `EVIDENTIA_RAW_BUCKET` should not be reused as deploy-time explicit names unless you intentionally want custom-named immutable resources.

## Outputs

The stack emits:

- raw/assets bucket names + ARNs
- S3 vectors bucket outputs:
  - `VectorsBucketArn`: ARN for IAM/data source wiring
  - `VectorsBucketName`: CloudFormation `Ref` value for `AWS::S3Vectors::VectorBucket` (can appear as an ARN in practice)
- S3 vectors index name + ARN
- recommended prefix templates
- KB role ARN
- API role ARN
- Bedrock Knowledge Base ID / ARN (when enabled)
- Bedrock Data Source ID (when enabled)

## Cleanup Redundant Buckets

Failed deploy attempts can leave extra S3 buckets behind. Use the repo script below from the project root:

```bash
# dry-run (safe): lists candidates only
./scripts/cleanup_redundant_s3_buckets.sh --region us-east-1 --stack-name EvidentiaFoundation-dev

# execute deletion
./scripts/cleanup_redundant_s3_buckets.sh --region us-east-1 --stack-name EvidentiaFoundation-dev --execute
```

Notes:

- This script deletes only classic S3 buckets (`aws s3api list-buckets`), not S3 Vectors resources.
- The script keeps active stack buckets from CloudFormation outputs (`RawBucketName`, `AssetsBucketName`, `VectorsBucketName`).
- It filters by prefix (defaults to `<lowercase-stack-name>-`) and skips `cdk-hnb659fds-*`.
- Override prefix with `--prefix` when needed.

For stale **S3 Vectors** resources (vector indexes + vector buckets), use:

```bash
# dry-run (safe)
./scripts/cleanup_redundant_s3vectors.sh --region us-east-1 --stack-name EvidentiaFoundation-dev

# execute deletion (indexes first, then vector buckets)
./scripts/cleanup_redundant_s3vectors.sh --region us-east-1 --stack-name EvidentiaFoundation-dev --execute
```

Notes:

- This script keeps the active vector bucket from stack outputs (`VectorsBucketName` / `VectorsBucketArn`).
- It targets vector buckets by prefix (default `<lowercase-stack-name>-s3vectorsbucket`).
- Vector bucket deletion requires all indexes to be deleted first; the script handles that ordering.
