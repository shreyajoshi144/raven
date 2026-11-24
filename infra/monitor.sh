#!/bin/sh
# Polls Raven's health endpoints and posts to ALERT_WEBHOOK_URL (Slack/Discord/Teams-compatible {"text": ...}) when the state changes.
# Env: RAVEN_URL (http://api:8000), ALERT_WEBHOOK_URL, MONITOR_INTERVAL_SECONDS (60), MONITOR_FAILS (2 consecutive failures before alerting), RUN_ONCE=1.
set -u
URL="${RAVEN_URL:-http://api:8000}"; fails=0; alerted=0
check() {
  for p in /health/ready /health/orchestrator; do
    curl -fsS -m 10 -o /dev/null "$URL$p" 2>/dev/null || { echo "$p"; return 1; }
  done
}
notify() {
  echo "$1"
  [ -n "${ALERT_WEBHOOK_URL:-}" ] && curl -fsS -m 10 -H 'Content-Type: application/json' -d "{\"text\":\"$1\"}" "$ALERT_WEBHOOK_URL" >/dev/null 2>&1
  return 0
}
while true; do
  if bad=$(check); then
    fails=0; [ "$alerted" = 1 ] && { alerted=0; notify "Raven RECOVERED: health checks pass again ($URL)"; }
  else
    fails=$((fails + 1))
    [ "$fails" -ge "${MONITOR_FAILS:-2}" ] && [ "$alerted" = 0 ] && { alerted=1; notify "Raven ALERT: $bad failing at $URL"; }
  fi
  [ "${RUN_ONCE:-0}" = "1" ] && exit 0
  sleep "${MONITOR_INTERVAL_SECONDS:-60}"
done
