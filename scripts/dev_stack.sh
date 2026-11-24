#!/usr/bin/env bash
# Starts a local dev/e2e stack WITHOUT Docker: Postgres must already be running.
# Usage: scripts/dev_stack.sh start|stop   (state in /tmp/raven-stack)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN=/tmp/raven-stack; mkdir -p "$RUN"
PY="${PYTHON:-python3}"
export APP_ENV=development ALLOW_CUSTOM_UPSTREAMS=true
export DATABASE_URL="${DATABASE_URL:-postgresql://raven:raven_dev_pw@127.0.0.1:5432/raven}"
export GITHUB_API_BASE_URL="${GITHUB_API_BASE_URL:-http://127.0.0.1:9101}"
export LLM_BASE_URL="${LLM_BASE_URL:-http://127.0.0.1:9102}" LLM_API_KEY="${LLM_API_KEY:-e2e-fake-key-0123456789}" LLM_MODEL="${LLM_MODEL:-claude-sonnet-5-5}"
export APP_SECRET_KEY="${APP_SECRET_KEY:-e2e-app-secret-key-0123456789abcdef012}" INTERNAL_SERVICE_SECRET="${INTERNAL_SERVICE_SECRET:-e2e-internal-secret-0123456789abcdef0}"
export N8N_WEBHOOK_SECRET="${N8N_WEBHOOK_SECRET:-e2e-webhook-secret-0123456789abcdef012}" N8N_BASE_URL="${N8N_BASE_URL:-http://127.0.0.1:5678}"
export LOG_LEVEL=INFO WORKER_POLL_SECONDS=0.5 RETRY_BASE_SECONDS=2 RETRY_MAX_SECONDS=8
case "${1:-start}" in
  start)
    cd "$ROOT/backend"; $PY -m alembic upgrade head >/dev/null
    setsid nohup $PY "$ROOT/e2e/fake_services.py" >"$RUN/fake.log" 2>&1 </dev/null & echo $! >"$RUN/fake.pid"
    setsid nohup $PY -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >"$RUN/api.log" 2>&1 </dev/null & echo $! >"$RUN/api.pid"
    setsid nohup $PY -m app.workers.main >"$RUN/worker.log" 2>&1 </dev/null & echo $! >"$RUN/worker.pid"
    sleep 3; curl -fsS http://127.0.0.1:8000/health/ready && echo ;;
  stop) for f in fake api worker; do [ -f "$RUN/$f.pid" ] && kill "$(cat "$RUN/$f.pid")" 2>/dev/null || true; done ;;
esac
