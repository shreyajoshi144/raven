#!/usr/bin/env bash
# Builds a clean source ZIP (no caches, no .env, no node_modules).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; OUT="${1:-$ROOT/../raven-mvp-source.zip}"
cd "$ROOT/.."
rm -f "$OUT"
zip -qr "$OUT" "$(basename "$ROOT")" -x '*/__pycache__/*' '*.pyc' '*/.env' '*/.pytest_cache/*' '*/.ruff_cache/*' '*/node_modules/*' '*/.venv/*' '*.zip' '*/e2e/__pycache__/*'
echo "wrote $OUT"; unzip -l "$OUT" | tail -1
