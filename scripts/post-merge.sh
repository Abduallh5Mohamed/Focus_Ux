#!/bin/bash
# Runs automatically after a task merge: sync Python and web dependencies.
set -e
cd "$(dirname "$0")/.."

uv sync --frozen
npm --prefix product/apps/web ci --no-audit --no-fund
