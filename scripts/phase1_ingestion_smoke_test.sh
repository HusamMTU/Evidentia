#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  phase1_ingestion_smoke_test.sh --file <path-to-pdf> [options]

Options:
  --file <path>          Local PDF file to upload for smoke test (required)
  --doc-id <id>          Document ID used for raw object key and ingestion traceability (default: smoke-<utc timestamp>)
  --stack-name <name>    CloudFormation stack name (default: EvidentiaFoundation-dev)
  --region <region>      AWS region (required unless AWS_REGION/AWS_DEFAULT_REGION is set)
  --profile <profile>    AWS CLI profile to use
  --raw-bucket <name>    Override raw documents bucket name
  --assets-bucket <name> Override extracted assets bucket name
  --kb-id <id>           Override Bedrock knowledge base ID
  --data-source-id <id>  Override Bedrock data source ID
  --kb-name <name>       Knowledge base name for ID discovery fallback
  --data-source-name <name>
                          Data source name for ID discovery fallback
  --poll-seconds <n>     Poll interval in seconds (default: 15)
  --timeout-seconds <n>  Max wait time in seconds (default: 1800)
  -h, --help             Show this help

Examples:
  ./scripts/phase1_ingestion_smoke_test.sh \
    --region us-east-1 \
    --stack-name EvidentiaFoundation-dev \
    --file /path/to/sample.pdf

  ./scripts/phase1_ingestion_smoke_test.sh \
    --region us-east-1 \
    --file ./docs/sample.pdf \
    --doc-id phase1-smoke-001
EOF
}

stack_name="EvidentiaFoundation-dev"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
profile=""
file_path=""
doc_id=""
raw_bucket="${EVIDENTIA_RAW_BUCKET:-}"
assets_bucket="${EVIDENTIA_ASSETS_BUCKET:-}"
kb_id="${BEDROCK_KNOWLEDGE_BASE_ID:-}"
data_source_id="${BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_ID:-}"
kb_name="${BEDROCK_KNOWLEDGE_BASE_NAME:-}"
data_source_name="${BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_NAME:-}"
poll_seconds=15
timeout_seconds=1800

while [[ $# -gt 0 ]]; do
  case "$1" in
    --file)
      file_path="${2:-}"
      shift 2
      ;;
    --doc-id)
      doc_id="${2:-}"
      shift 2
      ;;
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
    --raw-bucket)
      raw_bucket="${2:-}"
      shift 2
      ;;
    --assets-bucket)
      assets_bucket="${2:-}"
      shift 2
      ;;
    --kb-id)
      kb_id="${2:-}"
      shift 2
      ;;
    --data-source-id)
      data_source_id="${2:-}"
      shift 2
      ;;
    --kb-name)
      kb_name="${2:-}"
      shift 2
      ;;
    --data-source-name)
      data_source_name="${2:-}"
      shift 2
      ;;
    --poll-seconds)
      poll_seconds="${2:-}"
      shift 2
      ;;
    --timeout-seconds)
      timeout_seconds="${2:-}"
      shift 2
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

if [[ -z "$file_path" ]]; then
  echo "--file is required." >&2
  usage
  exit 1
fi

if [[ ! -f "$file_path" ]]; then
  echo "File not found: $file_path" >&2
  exit 1
fi

if [[ -z "$doc_id" ]]; then
  doc_id="smoke-$(date -u +%Y%m%dT%H%M%SZ)"
fi

aws_args=(--region "$region")
if [[ -n "$profile" ]]; then
  aws_args+=(--profile "$profile")
fi

get_stack_output() {
  local output_key="$1"
  local value
  value="$(aws "${aws_args[@]}" cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --query "Stacks[0].Outputs[?OutputKey=='${output_key}'].OutputValue" \
    --output text 2>/dev/null || true)"
  if [[ -z "$value" || "$value" == "None" ]]; then
    return 1
  fi
  printf "%s" "$value"
}

resolve_kb_id_from_name() {
  local name="$1"
  local id
  id="$(aws "${aws_args[@]}" bedrock-agent list-knowledge-bases \
    --query "knowledgeBaseSummaries[?name=='${name}'] | [0].knowledgeBaseId" \
    --output text 2>/dev/null || true)"
  if [[ -z "$id" || "$id" == "None" ]]; then
    return 1
  fi
  printf "%s" "$id"
}

resolve_data_source_id_from_name() {
  local kb_identifier="$1"
  local name="$2"
  local id
  id="$(aws "${aws_args[@]}" bedrock-agent list-data-sources \
    --knowledge-base-id "$kb_identifier" \
    --query "dataSourceSummaries[?name=='${name}'] | [0].dataSourceId" \
    --output text 2>/dev/null || true)"
  if [[ -z "$id" || "$id" == "None" ]]; then
    return 1
  fi
  printf "%s" "$id"
}

none_to_zero() {
  local value="${1:-}"
  if [[ -z "$value" || "$value" == "None" ]]; then
    printf "0"
  else
    printf "%s" "$value"
  fi
}

bucket_exists() {
  local bucket_name="$1"
  aws "${aws_args[@]}" s3api head-bucket --bucket "$bucket_name" >/dev/null 2>&1
}

knowledge_base_exists() {
  local kb_identifier="$1"
  aws "${aws_args[@]}" bedrock-agent get-knowledge-base \
    --knowledge-base-id "$kb_identifier" \
    --query "knowledgeBase.knowledgeBaseId" \
    --output text >/dev/null 2>&1
}

data_source_exists() {
  local kb_identifier="$1"
  local ds_identifier="$2"
  aws "${aws_args[@]}" bedrock-agent get-data-source \
    --knowledge-base-id "$kb_identifier" \
    --data-source-id "$ds_identifier" \
    --query "dataSource.dataSourceId" \
    --output text >/dev/null 2>&1
}

raw_bucket_from_stack="$(get_stack_output "RawBucketName" || true)"
assets_bucket_from_stack="$(get_stack_output "AssetsBucketName" || true)"
kb_id_from_stack="$(get_stack_output "BedrockKnowledgeBaseId" || true)"
data_source_id_from_stack="$(get_stack_output "BedrockKnowledgeBaseDataSourceId" || true)"
if [[ -z "$raw_bucket" ]]; then
  raw_bucket="$raw_bucket_from_stack"
fi
if [[ -z "$assets_bucket" ]]; then
  assets_bucket="$assets_bucket_from_stack"
fi
if [[ -z "$kb_id" ]]; then
  kb_id="$kb_id_from_stack"
fi
if [[ -z "$data_source_id" ]]; then
  data_source_id="$data_source_id_from_stack"
fi

if [[ -z "$kb_id" && -n "$kb_name" ]]; then
  kb_id="$(resolve_kb_id_from_name "$kb_name" || true)"
fi
if [[ -z "$data_source_id" && -n "$kb_id" && -n "$data_source_name" ]]; then
  data_source_id="$(resolve_data_source_id_from_name "$kb_id" "$data_source_name" || true)"
fi

if [[ -n "$raw_bucket" ]] && ! bucket_exists "$raw_bucket"; then
  if [[ -n "$raw_bucket_from_stack" && "$raw_bucket_from_stack" != "$raw_bucket" ]] && bucket_exists "$raw_bucket_from_stack"; then
    echo "Warning: raw bucket '$raw_bucket' not found; using stack output '$raw_bucket_from_stack' instead."
    raw_bucket="$raw_bucket_from_stack"
  fi
fi

if [[ -n "$assets_bucket" ]] && ! bucket_exists "$assets_bucket"; then
  if [[ -n "$assets_bucket_from_stack" && "$assets_bucket_from_stack" != "$assets_bucket" ]] && bucket_exists "$assets_bucket_from_stack"; then
    echo "Warning: assets bucket '$assets_bucket' not found; using stack output '$assets_bucket_from_stack' instead."
    assets_bucket="$assets_bucket_from_stack"
  fi
fi

if [[ -n "$kb_id" ]] && ! knowledge_base_exists "$kb_id"; then
  if [[ -n "$kb_id_from_stack" && "$kb_id_from_stack" != "$kb_id" ]] && knowledge_base_exists "$kb_id_from_stack"; then
    echo "Warning: knowledge base '$kb_id' not found; using stack output '$kb_id_from_stack' instead."
    kb_id="$kb_id_from_stack"
  fi
fi

if [[ -n "$data_source_id" ]] && ! data_source_exists "$kb_id" "$data_source_id"; then
  if [[ -n "$kb_id_from_stack" && -n "$data_source_id_from_stack" ]] && data_source_exists "$kb_id_from_stack" "$data_source_id_from_stack"; then
    if [[ "$kb_id" != "$kb_id_from_stack" || "$data_source_id" != "$data_source_id_from_stack" ]]; then
      echo "Warning: data source '$data_source_id' (kb '$kb_id') not found; using stack outputs '${data_source_id_from_stack}' (kb '${kb_id_from_stack}') instead."
    fi
    kb_id="$kb_id_from_stack"
    data_source_id="$data_source_id_from_stack"
  fi
fi

if [[ -z "$kb_id" && -n "$kb_name" ]]; then
  kb_id="$(resolve_kb_id_from_name "$kb_name" || true)"
fi
if [[ -z "$data_source_id" && -n "$kb_id" && -n "$data_source_name" ]]; then
  data_source_id="$(resolve_data_source_id_from_name "$kb_id" "$data_source_name" || true)"
fi

if [[ -z "$raw_bucket" ]]; then
  echo "Unable to resolve raw bucket. Set EVIDENTIA_RAW_BUCKET, pass --raw-bucket, or provide stack outputs." >&2
  exit 1
fi
if [[ -z "$assets_bucket" ]]; then
  echo "Unable to resolve assets bucket. Set EVIDENTIA_ASSETS_BUCKET, pass --assets-bucket, or provide stack outputs." >&2
  exit 1
fi
if [[ -z "$kb_id" ]]; then
  echo "Unable to resolve knowledge base ID. Set BEDROCK_KNOWLEDGE_BASE_ID, pass --kb-id, set BEDROCK_KNOWLEDGE_BASE_NAME/--kb-name, or enable KB outputs on the stack." >&2
  exit 1
fi
if [[ -z "$data_source_id" ]]; then
  echo "Unable to resolve data source ID. Set BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_ID, pass --data-source-id, set BEDROCK_KNOWLEDGE_BASE_DATA_SOURCE_NAME/--data-source-name, or enable KB outputs on the stack." >&2
  exit 1
fi

if ! bucket_exists "$raw_bucket"; then
  echo "Resolved raw bucket '$raw_bucket' does not exist. Update .env, pass --raw-bucket, or verify stack outputs." >&2
  exit 1
fi
if ! bucket_exists "$assets_bucket"; then
  echo "Resolved assets bucket '$assets_bucket' does not exist. Update .env, pass --assets-bucket, or verify stack outputs." >&2
  exit 1
fi
if ! knowledge_base_exists "$kb_id"; then
  echo "Resolved knowledge base '$kb_id' does not exist. Update .env, pass --kb-id, or verify stack outputs." >&2
  exit 1
fi
if ! data_source_exists "$kb_id" "$data_source_id"; then
  echo "Resolved data source '$data_source_id' does not exist for knowledge base '$kb_id'. Update .env, pass --data-source-id, or verify stack outputs." >&2
  exit 1
fi

raw_key="documents-raw/${doc_id}/source.pdf"
legacy_assets_prefix="documents-assets/${doc_id}/"
bedrock_assets_prefix="aws/bedrock/knowledge_bases/${kb_id}/${data_source_id}/"

echo "Phase 1 Ingestion Smoke Test"
echo "Stack: $stack_name"
echo "Region: $region"
echo "Doc ID: $doc_id"
echo "File: $file_path"
echo "Raw bucket: $raw_bucket"
echo "Assets bucket: $assets_bucket"
echo "Knowledge base ID: $kb_id"
echo "Data source ID: $data_source_id"
if [[ -n "$kb_name" ]]; then
  echo "Knowledge base name hint: $kb_name"
fi
if [[ -n "$data_source_name" ]]; then
  echo "Data source name hint: $data_source_name"
fi
echo

echo "1) Uploading source PDF to s3://${raw_bucket}/${raw_key}"
aws "${aws_args[@]}" s3 cp "$file_path" "s3://${raw_bucket}/${raw_key}"
aws "${aws_args[@]}" s3api head-object --bucket "$raw_bucket" --key "$raw_key" >/dev/null

description="Phase 1 smoke ingestion for ${doc_id}"
echo "2) Starting ingestion job"
ingestion_job_id="$(aws "${aws_args[@]}" bedrock-agent start-ingestion-job \
  --knowledge-base-id "$kb_id" \
  --data-source-id "$data_source_id" \
  --description "$description" \
  --query "ingestionJob.ingestionJobId" \
  --output text)"

if [[ -z "$ingestion_job_id" || "$ingestion_job_id" == "None" ]]; then
  echo "Failed to start ingestion job." >&2
  exit 1
fi
echo "Ingestion job ID: $ingestion_job_id"

echo "3) Polling ingestion job status"
started_epoch="$(date +%s)"
final_status=""
stats_scanned="0"
stats_new="0"
stats_modified="0"
stats_failed="0"

while true; do
  read -r status scanned new modified failed <<<"$(aws "${aws_args[@]}" bedrock-agent get-ingestion-job \
    --knowledge-base-id "$kb_id" \
    --data-source-id "$data_source_id" \
    --ingestion-job-id "$ingestion_job_id" \
    --query "[ingestionJob.status,ingestionJob.statistics.numberOfDocumentsScanned,ingestionJob.statistics.numberOfNewDocumentsIndexed,ingestionJob.statistics.numberOfModifiedDocumentsIndexed,ingestionJob.statistics.numberOfDocumentsFailed]" \
    --output text)"

  stats_scanned="$(none_to_zero "${scanned:-}")"
  stats_new="$(none_to_zero "${new:-}")"
  stats_modified="$(none_to_zero "${modified:-}")"
  stats_failed="$(none_to_zero "${failed:-}")"
  final_status="$status"

  elapsed=$(( $(date +%s) - started_epoch ))
  echo "  - status=${status} elapsed=${elapsed}s scanned=${stats_scanned} new=${stats_new} modified=${stats_modified} failed=${stats_failed}"

  case "$status" in
    COMPLETE)
      break
      ;;
    FAILED|STOPPED)
      reasons="$(aws "${aws_args[@]}" bedrock-agent get-ingestion-job \
        --knowledge-base-id "$kb_id" \
        --data-source-id "$data_source_id" \
        --ingestion-job-id "$ingestion_job_id" \
        --query "ingestionJob.failureReasons" \
        --output text)"
      echo "Ingestion job ended with status ${status}. Reasons: ${reasons}" >&2
      exit 1
      ;;
  esac

  if (( elapsed >= timeout_seconds )); then
    echo "Timed out after ${timeout_seconds}s waiting for ingestion job ${ingestion_job_id}." >&2
    exit 1
  fi
  sleep "$poll_seconds"
done

indexed_total=$((stats_new + stats_modified))
failure_reasons_text=""
if (( stats_failed > 0 )); then
  failure_reasons_text="$(aws "${aws_args[@]}" bedrock-agent get-ingestion-job \
    --knowledge-base-id "$kb_id" \
    --data-source-id "$data_source_id" \
    --ingestion-job-id "$ingestion_job_id" \
    --query "ingestionJob.failureReasons" \
    --output text || true)"
  if [[ -z "$failure_reasons_text" || "$failure_reasons_text" == "None" ]]; then
    failure_reasons_text="(no failureReasons returned by API)"
  fi
fi

if (( indexed_total < 1 )); then
  echo "Ingestion completed but indexed_total=${indexed_total}. Expected at least 1 indexed/updated document for a new smoke doc_id." >&2
  if (( stats_failed > 0 )); then
    echo "Failure reasons: ${failure_reasons_text}" >&2
  fi
  exit 1
fi

if (( stats_failed > 0 )); then
  echo "Ingestion completed with indexed_total=${indexed_total} but failed=${stats_failed}. Treating as failure for smoke test." >&2
  echo "Failure reasons: ${failure_reasons_text}" >&2
  exit 1
fi

echo "4) Verifying assets availability"
echo "  - checking legacy/doc-scoped prefix: s3://${assets_bucket}/${legacy_assets_prefix}"
legacy_assets_key_count="$(aws "${aws_args[@]}" s3api list-objects-v2 \
  --bucket "$assets_bucket" \
  --prefix "$legacy_assets_prefix" \
  --query "KeyCount" \
  --output text)"
legacy_assets_key_count="$(none_to_zero "$legacy_assets_key_count")"

if (( legacy_assets_key_count > 0 )); then
  echo "  - legacy prefix assets found: ${legacy_assets_key_count}"
  asset_keys="$(aws "${aws_args[@]}" s3api list-objects-v2 \
    --bucket "$assets_bucket" \
    --prefix "$legacy_assets_prefix" \
    --max-items 5 \
    --query "Contents[].Key" \
    --output text || true)"
  if [[ -n "$asset_keys" && "$asset_keys" != "None" ]]; then
    echo "  - legacy sample asset keys: $asset_keys"
  fi
else
  echo "  - no legacy/doc-scoped assets found."
fi

echo "  - checking Bedrock-managed prefix: s3://${assets_bucket}/${bedrock_assets_prefix}"
bedrock_assets_key_count="$(aws "${aws_args[@]}" s3api list-objects-v2 \
  --bucket "$assets_bucket" \
  --prefix "$bedrock_assets_prefix" \
  --query "KeyCount" \
  --output text)"
bedrock_assets_key_count="$(none_to_zero "$bedrock_assets_key_count")"

if (( bedrock_assets_key_count > 0 )); then
  echo "  - bedrock-managed assets found: ${bedrock_assets_key_count}"
  bedrock_asset_keys="$(aws "${aws_args[@]}" s3api list-objects-v2 \
    --bucket "$assets_bucket" \
    --prefix "$bedrock_assets_prefix" \
    --max-items 5 \
    --query "Contents[].Key" \
    --output text || true)"
  if [[ -n "$bedrock_asset_keys" && "$bedrock_asset_keys" != "None" ]]; then
    echo "  - bedrock sample asset keys: $bedrock_asset_keys"
  fi
else
  echo "  - no Bedrock-managed assets found under the KB/data source prefix."
  echo "    (Text-only PDFs can legitimately produce zero extracted visual assets.)"
fi

assets_key_count=$((legacy_assets_key_count + bedrock_assets_key_count))

echo
echo "Smoke test PASS"
echo "Summary:"
echo "  raw_s3_uri=s3://${raw_bucket}/${raw_key}"
echo "  ingestion_job_id=${ingestion_job_id}"
echo "  final_status=${final_status}"
echo "  scanned=${stats_scanned} new=${stats_new} modified=${stats_modified} failed=${stats_failed}"
echo "  legacy_assets_key_count=${legacy_assets_key_count}"
echo "  bedrock_assets_key_count=${bedrock_assets_key_count}"
echo "  assets_key_count_total=${assets_key_count}"
