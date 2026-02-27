#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  cleanup_redundant_s3vectors.sh [options]

Options:
  --stack-name <name>     CloudFormation stack name (default: EvidentiaFoundation-dev)
  --region <region>       AWS region for CloudFormation + S3 Vectors calls (required unless AWS_REGION/AWS_DEFAULT_REGION is set)
  --bucket-prefix <pref>  Vector bucket prefix to target (default: lowercase(stack-name)-s3vectorsbucket)
  --profile <profile>     AWS CLI profile to use
  --execute               Delete candidate indexes + vector buckets (default is dry-run)
  --dry-run               Only print candidate resources (default)
  -h, --help              Show this help

Examples:
  ./scripts/cleanup_redundant_s3vectors.sh --region us-east-1
  ./scripts/cleanup_redundant_s3vectors.sh --region us-east-1 --execute
EOF
}

stack_name="EvidentiaFoundation-dev"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
bucket_prefix=""
profile=""
execute=false

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
    --bucket-prefix)
      bucket_prefix="${2:-}"
      shift 2
      ;;
    --profile)
      profile="${2:-}"
      shift 2
      ;;
    --execute)
      execute=true
      shift
      ;;
    --dry-run)
      execute=false
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

if [[ -z "$bucket_prefix" ]]; then
  bucket_prefix="$(printf "%s" "$stack_name" | tr '[:upper:]' '[:lower:]')-s3vectorsbucket"
fi

aws_args=(--region "$region")
if [[ -n "$profile" ]]; then
  aws_args+=(--profile "$profile")
fi

extract_bucket_name() {
  local raw="$1"
  if [[ "$raw" == arn:aws:s3vectors:*:bucket/* ]]; then
    local rest="${raw#*bucket/}"
    printf "%s" "${rest%%/*}"
  else
    printf "%s" "$raw"
  fi
}

is_kept_bucket() {
  local candidate="$1"
  local keep
  for keep in "${kept_buckets[@]}"; do
    if [[ "$candidate" == "$keep" ]]; then
      return 0
    fi
  done
  return 1
}

echo "Stack: $stack_name"
echo "Region: $region"
echo "Bucket prefix: $bucket_prefix"
echo "Mode: $([[ "$execute" == true ]] && echo "execute" || echo "dry-run")"
echo

if ! stack_output_lines="$(aws "${aws_args[@]}" cloudformation describe-stacks \
  --stack-name "$stack_name" \
  --query "Stacks[0].Outputs[?OutputKey=='VectorsBucketName' || OutputKey=='VectorsBucketArn'].[OutputKey,OutputValue]" \
  --output text)"; then
  echo "Failed to read vector outputs for stack $stack_name in $region." >&2
  exit 1
fi

kept_buckets=()
while IFS=$'\t' read -r output_key output_value; do
  [[ -z "${output_value:-}" ]] && continue
  if [[ "$output_key" == "VectorsBucketName" || "$output_key" == "VectorsBucketArn" ]]; then
    kept_buckets+=("$(extract_bucket_name "$output_value")")
  fi
done < <(printf "%s\n" "$stack_output_lines" | sed '/^$/d')

if [[ ${#kept_buckets[@]} -eq 0 ]]; then
  echo "No active vector bucket found in stack outputs. Refusing to continue." >&2
  exit 1
fi

kept_buckets_sorted=()
while IFS= read -r line; do
  kept_buckets_sorted+=("$line")
done < <(printf "%s\n" "${kept_buckets[@]}" | sed '/^$/d' | sort -u)
kept_buckets=("${kept_buckets_sorted[@]}")

echo "Vector buckets in active stack (kept):"
for bucket in "${kept_buckets[@]}"; do
  echo "  - $bucket"
done
echo

if ! all_vector_bucket_text="$(aws "${aws_args[@]}" s3vectors list-vector-buckets \
  --prefix "$bucket_prefix" \
  --query "vectorBuckets[].vectorBucketName" \
  --output text)"; then
  echo "Failed to list S3 Vectors buckets in $region." >&2
  exit 1
fi

all_vector_buckets=()
while IFS= read -r bucket; do
  all_vector_buckets+=("$bucket")
done < <(printf "%s\n" "$all_vector_bucket_text" | tr '\t' '\n' | sed '/^$/d;/^None$/d')

candidate_buckets=()
for bucket in "${all_vector_buckets[@]}"; do
  if is_kept_bucket "$bucket"; then
    continue
  fi
  candidate_buckets+=("$bucket")
done

if [[ ${#candidate_buckets[@]} -eq 0 ]]; then
  echo "No redundant S3 Vectors buckets found for prefix '$bucket_prefix'."
  exit 0
fi

candidate_index_pairs=()
for bucket in "${candidate_buckets[@]}"; do
  if ! indexes_text="$(aws "${aws_args[@]}" s3vectors list-indexes \
    --vector-bucket-name "$bucket" \
    --query "indexes[].indexName" \
    --output text)"; then
    echo "Failed to list indexes for vector bucket '$bucket'." >&2
    exit 1
  fi
  while IFS= read -r index_name; do
    candidate_index_pairs+=("$bucket|$index_name")
  done < <(printf "%s\n" "$indexes_text" | tr '\t' '\n' | sed '/^$/d;/^None$/d')
done

echo "Redundant S3 Vectors bucket candidates:"
for bucket in "${candidate_buckets[@]}"; do
  echo "  - $bucket"
done
echo

if [[ ${#candidate_index_pairs[@]} -gt 0 ]]; then
  echo "Indexes that will be deleted first:"
  for pair in "${candidate_index_pairs[@]}"; do
    bucket_name="${pair%%|*}"
    index_name="${pair##*|}"
    echo "  - ${bucket_name}/${index_name}"
  done
  echo
fi

if [[ "$execute" != true ]]; then
  echo "Dry-run only. Re-run with --execute to delete these S3 Vectors resources."
  exit 0
fi

for pair in "${candidate_index_pairs[@]}"; do
  bucket_name="${pair%%|*}"
  index_name="${pair##*|}"
  echo "Deleting vector index: ${bucket_name}/${index_name}"
  aws "${aws_args[@]}" s3vectors delete-index \
    --vector-bucket-name "$bucket_name" \
    --index-name "$index_name"
done

for bucket in "${candidate_buckets[@]}"; do
  echo "Waiting for index deletion to settle in bucket: $bucket"
  attempts=0
  while true; do
    attempts=$((attempts + 1))
    remaining="$(aws "${aws_args[@]}" s3vectors list-indexes \
      --vector-bucket-name "$bucket" \
      --query "length(indexes)" \
      --output text)"
    if [[ "$remaining" == "0" ]]; then
      break
    fi
    if [[ $attempts -ge 20 ]]; then
      echo "Timed out waiting for indexes to clear in bucket '$bucket'." >&2
      exit 1
    fi
    sleep 3
  done

  echo "Deleting vector bucket: $bucket"
  aws "${aws_args[@]}" s3vectors delete-vector-bucket --vector-bucket-name "$bucket"
done

echo
echo "S3 Vectors cleanup complete."
