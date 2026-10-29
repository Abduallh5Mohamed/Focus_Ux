#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export FOCUS_API_STORAGE_ROOT="$PWD/runtime/replit/api"
export PYTHONPATH="$PWD/product:$PWD/product/packages/ml${PYTHONPATH:+:$PYTHONPATH}"
export VITE_API_BASE_URL=/api
export VITE_DEV_MOCK_API=0
python -m uvicorn services.api.focus_api.main:app --host 127.0.0.1 --port 8000 &
api_pid=$!
cleanup() {
  kill "$api_pid" "${web_pid:-}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
npm --prefix product/apps/web run dev &
web_pid=$!
wait -n "$api_pid" "$web_pid"
