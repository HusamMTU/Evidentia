#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  clean_reset_foundation.sh [options]

Destructively removes the current foundation stack and retained content/resources.
This automates the clean-reset flow up through Bedrock drift cleanup. It does not
redeploy the stack.

Options:
  --stack-name <name>           CloudFormation stack name (default: EvidentiaFoundation-dev)
  --region <region>             AWS region (required unless AWS_REGION/AWS_DEFAULT_REGION is set, or .env provides it)
  --profile <profile>           AWS CLI profile to use
  --env-file <path>             Env file to source for defaults (default: repo-root/.env when present)
  --skip-redundant-cleanup      Skip cleanup of redundant old S3 and S3 Vectors resources
  --skip-bedrock-cleanup        Skip optional Bedrock KB/data source drift cleanup
  --vector-wait-seconds <n>     Max wait for S3 Vectors index deletion (default: 1800)
  -h, --help                    Show this help

Examples:
  ./scripts/clean_reset_foundation.sh --region us-east-1
  ./scripts/clean_reset_foundation.sh --region us-east-1 --profile dev-admin
USAGE
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
default_env_file="${repo_root}/.env"
stack_name="EvidentiaFoundation-dev"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
profile=""
env_file="$default_env_file"
skip_redundant_cleanup=false
skip_bedrock_cleanup=false
vector_wait_seconds=1800

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

log_step() {
  printf '\n[%s] STEP %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

warn() {
  printf '[%s] WARN: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

die() {
  printf '[%s] ERROR: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
  exit 1
}

on_error() {
  local exit_code="$1"
  local line_number="$2"
  printf '[%s] ERROR: Command failed at line %s (exit %s).\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$line_number" "$exit_code" >&2
}
trap 'on_error $? $LINENO' ERR

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
    --skip-redundant-cleanup)
      skip_redundant_cleanup=true
      shift
      ;;
    --skip-bedrock-cleanup)
      skip_bedrock_cleanup=true
      shift
      ;;
    --vector-wait-seconds)
      vector_wait_seconds="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      die "Unknown argument: $1"
      ;;
  esac
done

if [[ -n "$env_file" && -f "$env_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
  if [[ -z "$region" ]]; then
    region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
  fi
fi

if ! command -v aws >/dev/null 2>&1; then
  die "aws CLI not found in PATH."
fi

if ! command -v cdk >/dev/null 2>&1; then
  die "cdk CLI not found in PATH."
fi

if [[ -z "$region" ]]; then
  die "Region is required. Set AWS_REGION/AWS_DEFAULT_REGION, add it to .env, or pass --region."
fi

if ! [[ "$vector_wait_seconds" =~ ^[0-9]+$ ]] || [[ "$vector_wait_seconds" -le 0 ]]; then
  die "--vector-wait-seconds must be a positive integer."
fi

export AWS_PAGER=""
aws_args=(--no-cli-pager --region "$region")
if [[ -n "$profile" ]]; then
  aws_args+=(--profile "$profile")
fi

aws_cli() {
  aws "${aws_args[@]}" "$@"
}

extract_vector_bucket_name() {
  local raw="$1"
  if [[ "$raw" == arn:aws:s3vectors:*:bucket/* ]]; then
    local remainder="${raw#*bucket/}"
    printf '%s' "${remainder%%/*}"
  else
    printf '%s' "$raw"
  fi
}

get_stack_output() {
  local output_key="$1"
  local value
  value="$(aws_cli cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --query "Stacks[0].Outputs[?OutputKey=='${output_key}'].OutputValue | [0]" \
    --output text 2>/dev/null || true)"
  if [[ -z "$value" || "$value" == "None" ]]; then
    return 1
  fi
  printf '%s' "$value"
}

stack_exists() {
  aws_cli cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --query 'Stacks[0].StackName' \
    --output text >/dev/null 2>&1
}

bucket_exists() {
  local bucket_name="$1"
  aws_cli s3api head-bucket --bucket "$bucket_name" >/dev/null 2>&1
}

table_exists() {
  local table_name="$1"
  aws_cli dynamodb describe-table \
    --table-name "$table_name" \
    --query 'Table.TableName' \
    --output text >/dev/null 2>&1
}

vector_bucket_exists() {
  local bucket_name="$1"
  [[ "$(aws_cli s3vectors list-vector-buckets \
    --prefix "$bucket_name" \
    --query "length(vectorBuckets[?vectorBucketName=='${bucket_name}'])" \
    --output text 2>/dev/null || true)" == "1" ]]
}

knowledge_base_exists() {
  local kb_id="$1"
  aws_cli bedrock-agent get-knowledge-base \
    --knowledge-base-id "$kb_id" \
    --query 'knowledgeBase.knowledgeBaseId' \
    --output text >/dev/null 2>&1
}

data_source_exists() {
  local kb_id="$1"
  local data_source_id="$2"
  aws_cli bedrock-agent get-data-source \
    --knowledge-base-id "$kb_id" \
    --data-source-id "$data_source_id" \
    --query 'dataSource.dataSourceId' \
    --output text >/dev/null 2>&1
}

wait_for_stack_delete() {
  local poll_seconds=10
  local waited=0
  local max_wait=1800
  while stack_exists; do
    if (( waited >= max_wait )); then
      die "Timed out waiting for stack $stack_name to delete."
    fi
    log "CloudFormation stack still exists; waiting ${poll_seconds}s..."
    sleep "$poll_seconds"
    waited=$((waited + poll_seconds))
  done
}

empty_versioned_bucket() {
  local bucket_name="$1"
  local pass=0
  local total_deleted=0

  if ! bucket_exists "$bucket_name"; then
    warn "Bucket $bucket_name does not exist; skipping."
    return 0
  fi

  log "Draining versioned S3 bucket: $bucket_name"
  while true; do
    pass=$((pass + 1))
    local rows
    rows="$(aws_cli s3api list-object-versions \
      --bucket "$bucket_name" \
      --query '[Versions[].[Key,VersionId], DeleteMarkers[].[Key,VersionId]][][]' \
      --output text 2>/dev/null || true)"

    if [[ -z "$rows" || "$rows" == "None" ]]; then
      break
    fi

    local pass_deleted=0
    while read -r key version_id; do
      [[ -z "${key:-}" || -z "${version_id:-}" ]] && continue
      aws_cli s3api delete-object \
        --bucket "$bucket_name" \
        --key "$key" \
        --version-id "$version_id" >/dev/null
      pass_deleted=$((pass_deleted + 1))
      total_deleted=$((total_deleted + 1))
      if (( pass_deleted % 100 == 0 )); then
        log "Deleted ${pass_deleted} versions/delete-markers in current pass from $bucket_name"
      fi
    done <<< "$rows"

    log "Pass ${pass}: deleted ${pass_deleted} versions/delete-markers from $bucket_name"
  done

  local multipart_uploads
  multipart_uploads="$(aws_cli s3api list-multipart-uploads \
    --bucket "$bucket_name" \
    --query 'Uploads[].[Key,UploadId]' \
    --output text 2>/dev/null || true)"

  if [[ -n "$multipart_uploads" && "$multipart_uploads" != "None" ]]; then
    log "Aborting in-flight multipart uploads for $bucket_name"
    while read -r key upload_id; do
      [[ -z "${key:-}" || -z "${upload_id:-}" ]] && continue
      aws_cli s3api abort-multipart-upload \
        --bucket "$bucket_name" \
        --key "$key" \
        --upload-id "$upload_id" >/dev/null
    done <<< "$multipart_uploads"
  fi

  aws_cli s3 rb "s3://$bucket_name"
  log "Deleted bucket $bucket_name (removed ${total_deleted} versioned objects/delete-markers first)"
}

delete_s3vectors_resources() {
  local bucket_name="$1"
  local wait_seconds="$2"

  if ! vector_bucket_exists "$bucket_name"; then
    warn "S3 Vectors bucket $bucket_name does not exist; skipping."
    return 0
  fi

  local index_names_text
  index_names_text="$(aws_cli s3vectors list-indexes \
    --vector-bucket-name "$bucket_name" \
    --query 'indexes[].indexName' \
    --output text)"

  local index_names=()
  while IFS= read -r index_name; do
    [[ -z "$index_name" || "$index_name" == "None" ]] && continue
    index_names+=("$index_name")
  done < <(printf '%s\n' "$index_names_text" | tr '\t' '\n')

  if [[ ${#index_names[@]} -eq 0 ]]; then
    log "No indexes found in vector bucket $bucket_name"
  else
    log "Deleting ${#index_names[@]} index(es) from vector bucket $bucket_name"
    local index_name
    for index_name in "${index_names[@]}"; do
      log "Deleting S3 Vectors index ${bucket_name}/${index_name}"
      aws_cli s3vectors delete-index \
        --vector-bucket-name "$bucket_name" \
        --index-name "$index_name" >/dev/null
    done
  fi

  local waited=0
  local poll_seconds=10
  while true; do
    local remaining_text
    remaining_text="$(aws_cli s3vectors list-indexes \
      --vector-bucket-name "$bucket_name" \
      --query 'indexes[].indexName' \
      --output text)"

    local remaining=()
    while IFS= read -r index_name; do
      [[ -z "$index_name" || "$index_name" == "None" ]] && continue
      remaining+=("$index_name")
    done < <(printf '%s\n' "$remaining_text" | tr '\t' '\n')

    if [[ ${#remaining[@]} -eq 0 ]]; then
      break
    fi

    if (( waited >= wait_seconds )); then
      die "Timed out waiting for S3 Vectors indexes to delete from $bucket_name. Remaining: ${remaining[*]}"
    fi

    log "Waiting for S3 Vectors indexes to delete from $bucket_name. Remaining: ${remaining[*]}"
    sleep "$poll_seconds"
    waited=$((waited + poll_seconds))
  done

  aws_cli s3vectors delete-vector-bucket --vector-bucket-name "$bucket_name" >/dev/null
  log "Deleted S3 Vectors bucket $bucket_name"
}

delete_manifest_table() {
  local table_name="$1"
  if ! table_exists "$table_name"; then
    warn "DynamoDB table $table_name does not exist; skipping."
    return 0
  fi

  aws_cli dynamodb delete-table --table-name "$table_name" >/dev/null
  log "Requested DynamoDB table deletion: $table_name"
}

delete_bedrock_drift_resources() {
  local kb_id="$1"
  local data_source_id="$2"

  if [[ -n "$data_source_id" && "$data_source_id" != "None" && -n "$kb_id" && "$kb_id" != "None" ]]; then
    if data_source_exists "$kb_id" "$data_source_id"; then
      aws_cli bedrock-agent delete-data-source \
        --knowledge-base-id "$kb_id" \
        --data-source-id "$data_source_id" >/dev/null
      log "Requested Bedrock data source deletion: kb=$kb_id data_source=$data_source_id"
    else
      warn "Bedrock data source $data_source_id in KB $kb_id was already absent."
    fi
  fi

  if [[ -n "$kb_id" && "$kb_id" != "None" ]]; then
    if knowledge_base_exists "$kb_id"; then
      aws_cli bedrock-agent delete-knowledge-base \
        --knowledge-base-id "$kb_id" >/dev/null
      log "Requested Bedrock knowledge base deletion: $kb_id"
    else
      warn "Bedrock knowledge base $kb_id was already absent."
    fi
  fi
}

log_step "1/8 Resolve configuration and validate prerequisites"
log "Repository root: $repo_root"
log "Stack name: $stack_name"
log "Region: $region"
if [[ -n "$profile" ]]; then
  log "AWS profile: $profile"
fi
if [[ -n "$env_file" && -f "$env_file" ]]; then
  log "Env file sourced for defaults: $env_file"
fi
if [[ ! -d "$repo_root/infra/cdk" ]]; then
  die "Expected infra/cdk directory at $repo_root/infra/cdk"
fi
if [[ ! -d "$repo_root/infra/cdk/.venv" ]]; then
  die "Expected CDK virtualenv at $repo_root/infra/cdk/.venv"
fi
if ! stack_exists; then
  die "CloudFormation stack $stack_name was not found in region $region."
fi

log_step "2/8 Optional cleanup of redundant old S3 and S3 Vectors resources"
if [[ "$skip_redundant_cleanup" == true ]]; then
  log "Skipping redundant resource cleanup by request."
else
  cleanup_args=(--region "$region" --stack-name "$stack_name" --execute)
  if [[ -n "$profile" ]]; then
    cleanup_args+=(--profile "$profile")
  fi

  "$script_dir/cleanup_redundant_s3_buckets.sh" \
    "${cleanup_args[@]}"

  "$script_dir/cleanup_redundant_s3vectors.sh" \
    "${cleanup_args[@]}"
fi

log_step "3/8 Capture retained resource names from stack outputs"
raw_bucket="$(get_stack_output 'RawBucketName')"
assets_bucket="$(get_stack_output 'AssetsBucketName')"
vectors_bucket_raw="$(get_stack_output 'VectorsBucketName' || get_stack_output 'VectorsBucketArn')"
vectors_bucket="$(extract_vector_bucket_name "$vectors_bucket_raw")"
manifest_table="$(get_stack_output 'IngestionManifestTableName')"
kb_id="$(get_stack_output 'BedrockKnowledgeBaseId' || true)"
data_source_id="$(get_stack_output 'BedrockKnowledgeBaseDataSourceId' || true)"

if [[ -z "$vectors_bucket" || "$vectors_bucket" == "None" ]]; then
  die "Failed to resolve S3 Vectors bucket name from stack outputs."
fi

log "Raw bucket: $raw_bucket"
log "Assets bucket: $assets_bucket"
log "Vectors bucket: $vectors_bucket"
if [[ "$vectors_bucket_raw" != "$vectors_bucket" ]]; then
  log "Normalized vectors bucket from output value: $vectors_bucket_raw -> $vectors_bucket"
fi
log "Manifest table: $manifest_table"
if [[ -n "$kb_id" && "$kb_id" != "None" ]]; then
  log "Bedrock knowledge base id: $kb_id"
fi
if [[ -n "$data_source_id" && "$data_source_id" != "None" ]]; then
  log "Bedrock data source id: $data_source_id"
fi

log_step "4/8 Destroy the CDK stack"
(
  cd "$repo_root/infra/cdk"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  if [[ -n "$env_file" && -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
  export AWS_REGION="$region"
  if [[ -n "$profile" ]]; then
    export AWS_PROFILE="$profile"
  fi
  export CDK_DEFAULT_ACCOUNT="$(aws_cli sts get-caller-identity --query 'Account' --output text)"
  export CDK_DEFAULT_REGION="$region"
  cdk destroy "$stack_name" --app ".venv/bin/python app.py" --force
)
wait_for_stack_delete
log "CloudFormation stack $stack_name deleted"

log_step "5/8 Empty and delete retained S3 buckets"
empty_versioned_bucket "$raw_bucket"
empty_versioned_bucket "$assets_bucket"

log_step "6/8 Delete S3 Vectors indexes and vector bucket"
delete_s3vectors_resources "$vectors_bucket" "$vector_wait_seconds"

log_step "7/8 Delete retained DynamoDB manifest table"
delete_manifest_table "$manifest_table"

log_step "8/8 Optional Bedrock drift cleanup"
if [[ "$skip_bedrock_cleanup" == true ]]; then
  log "Skipping Bedrock drift cleanup by request."
else
  delete_bedrock_drift_resources "$kb_id" "$data_source_id"
fi

log "Clean reset complete. Retained resources for $stack_name have been removed."
log "Next steps: reset .env if needed, redeploy the stack, then run ./scripts/sync_env_from_stack.sh"
