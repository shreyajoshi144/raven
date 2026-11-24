#!/bin/sh
# Imports (idempotently, fixed workflow IDs) and activates the Raven workflows, then starts n8n.
set -eu
WF_DIR="${RAVEN_WORKFLOW_DIR:-/raven/workflows}"
n8n import:workflow --separate --input="$WF_DIR"
for id in raven_repository_analysis raven_documentation_generation raven_codebase_qa; do
  n8n publish:workflow --id="$id" 2>/dev/null || n8n update:workflow --id="$id" --active=true
done
exec n8n start
