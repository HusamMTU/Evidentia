#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  cleanup_redundant_s3_buckets.sh [options]

Options:
  --stack-name <name>   CloudFormation stack name (default: EvidentiaFoundation-dev)
  --region <region>     AWS region for CloudFormation calls (required unless AWS_REGION/AWS_DEFAULT_REGION is set)
  --prefix <prefix>     Bucket name prefix to target (default: lowercase(stack-name)-)
  --profile <profile>   AWS CLI profile to use
  --execute             Delete candidate buckets (default is dry-run)
  --dry-run             Only print candidate buckets (default)
  -h, --help            Show this help

Examples:
  ./scripts/cleanup_redundant_s3_buckets.sh --region us-east-1
  ./scripts/cleanup_redundant_s3_buckets.sh --region us-east-1 --execute
EOF
}

stack_name="EvidentiaFoundation-dev"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
prefix=""
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
    --prefix)
      prefix="${2:-}"
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

if [[ -z "$prefix" ]]; then
  prefix="$(printf "%s" "$stack_name" | tr '[:upper:]' '[:lower:]')-"
fi

aws_args=(--region "$region")
if [[ -n "$profile" ]]; then
  aws_args+=(--profile "$profile")
fi

echo "Stack: $stack_name"
echo "Region: $region"
echo "Prefix: $prefix"
echo "Mode: $([[ "$execute" == true ]] && echo "execute" || echo "dry-run")"
echo

if ! keep_text="$(aws "${aws_args[@]}" cloudformation describe-stacks \
  --stack-name "$stack_name" \
  --query "Stacks[0].Outputs[?OutputKey=='RawBucketName' || OutputKey=='AssetsBucketName' || OutputKey=='VectorsBucketName'].OutputValue" \
  --output text)"; then
  echo "Failed to read stack outputs for $stack_name in $region." >&2
  exit 1
fi

keep_buckets=()
while IFS= read -r bucket; do
  keep_buckets+=("$bucket")
done < <(printf "%s\n" "$keep_text" | tr '\t' '\n' | sed '/^$/d' | sort -u)

if [[ ${#keep_buckets[@]} -eq 0 ]]; then
  echo "No keep-buckets found from stack outputs. Refusing to continue." >&2
  exit 1
fi

echo "Buckets in active stack (kept):"
for bucket in "${keep_buckets[@]}"; do
  echo "  - $bucket"
done
echo

all_text="$(aws "${aws_args[@]}" s3api list-buckets --query 'Buckets[].Name' --output text)"
all_buckets=()
while IFS= read -r bucket; do
  all_buckets+=("$bucket")
done < <(printf "%s\n" "$all_text" | tr '\t' '\n' | sed '/^$/d')

is_keep_bucket() {
  local candidate="$1"
  local keep
  for keep in "${keep_buckets[@]}"; do
    if [[ "$candidate" == "$keep" ]]; then
      return 0
    fi
  done
  return 1
}

candidates=()
for bucket in "${all_buckets[@]}"; do
  if [[ "$bucket" != "$prefix"* ]]; then
    continue
  fi
  if [[ "$bucket" == cdk-hnb659fds-* ]]; then
    continue
  fi
  if is_keep_bucket "$bucket"; then
    continue
  fi
  candidates+=("$bucket")
done

if [[ ${#candidates[@]} -eq 0 ]]; then
  echo "No redundant S3 buckets found for prefix '$prefix'."
  exit 0
fi

echo "Redundant S3 bucket candidates:"
for bucket in "${candidates[@]}"; do
  echo "  - $bucket"
done
echo

if [[ "$execute" != true ]]; then
  echo "Dry-run only. Re-run with --execute to delete these buckets."
  exit 0
fi

failures=()
for bucket in "${candidates[@]}"; do
  echo "Deleting s3://$bucket"
  if ! aws "${aws_args[@]}" s3 rb "s3://$bucket" --force; then
    failures+=("$bucket")
  fi
done

if [[ ${#failures[@]} -gt 0 ]]; then
  echo
  echo "Failed to delete some buckets:"
  for bucket in "${failures[@]}"; do
    echo "  - $bucket"
  done
  exit 1
fi

echo
echo "Cleanup complete."
