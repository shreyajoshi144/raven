#!/usr/bin/env bash
# Brings up Postgres + API + worker + fake GitHub/LLM + workflow interpreter for local e2e (no Docker).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
pg_lsclusters | tail -1 | grep -q online || { (setsid nohup pg_ctlcluster 16 main start >/dev/null 2>&1 </dev/null &); sleep 6; }
. /home/claude/venv/bin/activate
PYTHON=python scripts/dev_stack.sh stop >/dev/null 2>&1; pkill -f workflow_runner.mjs 2>/dev/null; sleep 1
PGPASSWORD=raven_dev_pw psql -h 127.0.0.1 -U raven -d raven -qc "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" >/dev/null 2>&1
PYTHON=python scripts/dev_stack.sh start >/dev/null 2>&1
export RAVEN_API_BASE_URL=http://127.0.0.1:8000 INTERNAL_SERVICE_SECRET=e2e-internal-secret-0123456789abcdef0 N8N_WEBHOOK_SECRET=e2e-webhook-secret-0123456789abcdef012 N8N_SELF_URL=http://127.0.0.1:5678 WAIT_SCALE=0.3 RAVEN_MAX_ANALYSIS_SECONDS=120
(setsid nohup /opt/node24/node_modules/.bin/node e2e/workflow_runner.mjs automation/n8n > /tmp/raven-stack/runner.log 2>&1 < /dev/null &)
sleep 5; curl -s http://127.0.0.1:8000/health/ready; echo; curl -s http://127.0.0.1:8000/health/orchestrator; echo
