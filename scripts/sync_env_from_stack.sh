#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  sync_env_from_stack.sh [options]

Options:
  --stack-name <name>   CloudFormation stack name (default: EvidentiaFoundation-dev)
  --region <region>     AWS region (required unless AWS_REGION/AWS_DEFAULT_REGION is set)
  --profile <profile>   AWS CLI profile to use
  --env-file <path>     .env file to update (default: .env)
  --dry-run             Print planned updates without writing file
  -h, --help            Show this help

Examples:
  ./scripts/sync_env_from_stack.sh --region us-east-1
  ./scripts/sync_env_from_stack.sh --region us-east-1 --stack-name EvidentiaFoundation-prod
EOF
}

stack_name="EvidentiaFoundation-dev"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
profile=""
env_file=".env"
dry_run=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stack-name)
      stack_name="${2:-}"
      shift 2
      ;;
    --region)
      region="${2:-}"
      shift 2
      ;;
    --profile)
      profile="${2:-}"
      shift 2
      ;;
    --env-file)
      env_file="${2:-}"
      shift 2
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not found in PATH." >&2
  exit 1
fi

if [[ -z "$region" ]]; then
  echo "Region is required. Set AWS_REGION/AWS_DEFAULT_REGION or pass --region." >&2
  exit 1
fi

if [[ ! -f "$env_file" ]]; then
  echo "Env file not found: $env_file" >&2
  echo "Create it first (for example: cp .env.example .env)." >&2
  exit 1
fi

aws_args=(--region "$region")
if [[ -n "$profile" ]]; then
  aws_args+=(--profile "$profile")
fi

if ! aws "${aws_args[@]}" cloudformation describe-stacks --stack-name "$stack_name" >/dev/null 2>&1; then
  echo "CloudFormation stack not found: $stack_name (region: $region)" >&2
  exit 1
fi

get_output() {
  local output_key="$1"
  local value
  value="$(aws "${aws_args[@]}" cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --query "Stacks[0].Outputs[?OutputKey=='${output_key}'].OutputValue" \
    --output text 2>/dev/null || true)"
  if [[ -z "$value" || "$value" == "None" ]]; then
    printf ""
  else
    printf "%s" "$value"
  fi
}

set_env_key() {
  local key="$1"
  local value="$2"
  local file="$3"
  local tmp_file
  tmp_file="$(mktemp)"
  awk -v k="$key" -v v="$value" '
    BEGIN { replaced = 0 }
    $0 ~ ("^" k "=") {
      if (replaced == 0) {
        print k "=" v
        replaced = 1
      }
      next
    }
    { print }
    END {
      if (replaced == 0) {
        print k "=" v
      }
    }
  ' "$file" > "$tmp_file"
  mv "$tmp_file" "$file"
}

value_evidentia_raw_bucket="$(get_output "RawBucketName")"
value_evidentia_assets_bucket="$(get_output "AssetsBucketName")"
value_evidentia_vectors_bucket="$(get_output "VectorsBucketArn")"
value_evidentia_api_role_arn="$(get_output "ApiRuntimeRoleArn")"
value_evidentia_ingestion_manifest_table_name="$(get_output "IngestionManifestTableName")"
value_evidentia_ingestion_manifest_source_uri_index="$(get_output "IngestionManifestSourceUriIndexName")"
value_bedrock_kb_id="$(get_output "BedrockKnowledgeBaseId")"
value_bedrock_data_source_id="$(get_output "BedrockKnowledgeBaseDataSourceId")"
value_bedrock_s3_vectors_index_name="$(get_output "S3VectorsIndexName")"

value_for_key() {
  local key="$1"
  case "$key" in
    EVIDENTIA_RAW_BUCKET) printf "%s" "$value_evidentia_raw_bucket" ;;
    EVIDENTIA_ASSETS_BUCKET) printf "%s" "$value_evidentia_assets_bucket" ;;
    EVIDENTIA_VECTORS_BUCKET) printf "%s" "$value_evidentia_vectors_bucket" ;;
    EVIDENTIA_API_ROLE_ARN) printf "%s" "$value_evidentia_api_role_arn" ;;
    EVIDENTIA_INGESTION_MANIFEST_TABLE_NAME) printf "%s" "$value_evidentia_ingestion_manifest_table_name" ;;
    EVIDENTIA_INGESTION_MANIFEST_SOURCE_URI_INDEX) printf "%s" "$value_evidentia_ingestion_manifest_source_uri_index" ;;
    BEDROCK_KNOWLEDGE_BASE_ID) printf "%s" "$value_bedrock_kb_id" ;;
    BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_ID) printf "%s" "$value_bedrock_data_source_id" ;;
    BEDROCK_S3_VECTORS_INDEX_NAME) printf "%s" "$value_bedrock_s3_vectors_index_name" ;;
    *) return 1 ;;
  esac
}

required_keys=(
  "EVIDENTIA_RAW_BUCKET"
  "EVIDENTIA_ASSETS_BUCKET"
  "EVIDENTIA_VECTORS_BUCKET"
  "EVIDENTIA_API_ROLE_ARN"
  "EVIDENTIA_INGESTION_MANIFEST_TABLE_NAME"
  "EVIDENTIA_INGESTION_MANIFEST_SOURCE_URI_INDEX"
  "BEDROCK_S3_VECTORS_INDEX_NAME"
)

for key in "${required_keys[@]}"; do
  if [[ -z "$(value_for_key "$key")" ]]; then
    echo "Missing required stack output mapping for $key (stack: $stack_name)." >&2
    exit 1
  fi
done

echo "Stack: $stack_name"
echo "Region: $region"
echo "Env file: $env_file"
echo
echo "Values to apply:"
for key in \
  EVIDENTIA_RAW_BUCKET \
  EVIDENTIA_ASSETS_BUCKET \
  EVIDENTIA_VECTORS_BUCKET \
  EVIDENTIA_API_ROLE_ARN \
  EVIDENTIA_INGESTION_MANIFEST_TABLE_NAME \
  EVIDENTIA_INGESTION_MANIFEST_SOURCE_URI_INDEX \
  BEDROCK_KNOWLEDGE_BASE_ID \
  BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_ID \
  BEDROCK_S3_VECTORS_INDEX_NAME
do
  value="$(value_for_key "$key")"
  if [[ -z "$value" ]]; then
    echo "  - $key=<empty>"
  else
    echo "  - $key=$value"
  fi
done
echo

if [[ "$dry_run" == true ]]; then
  echo "Dry-run mode: no file changes made."
  exit 0
fi

for key in \
  EVIDENTIA_RAW_BUCKET \
  EVIDENTIA_ASSETS_BUCKET \
  EVIDENTIA_VECTORS_BUCKET \
  EVIDENTIA_API_ROLE_ARN \
  EVIDENTIA_INGESTION_MANIFEST_TABLE_NAME \
  EVIDENTIA_INGESTION_MANIFEST_SOURCE_URI_INDEX \
  BEDROCK_KNOWLEDGE_BASE_ID \
  BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_ID \
  BEDROCK_S3_VECTORS_INDEX_NAME
do
  set_env_key "$key" "$(value_for_key "$key")" "$env_file"
done

echo "Updated $env_file from stack outputs."
