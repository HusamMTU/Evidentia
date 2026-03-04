#!/usr/bin/env bash
set -euo pipefail

host="127.0.0.1"
port="8787"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      host="${2:-}"
      shift 2
      ;;
    --port)
      port="${2:-}"
      shift 2
      ;;
    -h|--help)
      cat <<'EOF'
Usage:
  run_s3_vectors_inspector.sh [--host <host>] [--port <port>]

Examples:
  ./scripts/run_s3_vectors_inspector.sh
  ./scripts/run_s3_vectors_inspector.sh --host 0.0.0.0 --port 8787
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

python_bin=".venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
  python_bin="python3"
fi

exec "$python_bin" tools/s3_vectors_inspector/server.py --host "$host" --port "$port"
