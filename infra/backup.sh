#!/bin/sh
# Daily PostgreSQL backup + housekeeping. Env: PGHOST PGUSER PGPASSWORD PGDATABASE, BACKUP_DIR (/backups), BACKUP_KEEP_DAYS (14),
# ANALYSIS_RETENTION_DAYS (0 = keep forever), BACKUP_INTERVAL_SECONDS (86400), RUN_ONCE=1 to run a single cycle.
set -eu
DIR="${BACKUP_DIR:-/backups}"; KEEP="${BACKUP_KEEP_DAYS:-14}"; RET="${ANALYSIS_RETENTION_DAYS:-0}"; mkdir -p "$DIR"
cycle() {
  f="$DIR/raven-$(date -u +%Y%m%dT%H%M%SZ).dump"
  pg_dump -Fc -f "$f.part" && mv "$f.part" "$f" && echo "backup ok: $f ($(wc -c <"$f") bytes)"
  find "$DIR" -name 'raven-*.dump' -mtime +"$KEEP" -delete
  # housekeeping: expired sessions and auth tokens, old rate-limit events, optional analysis retention (cascades to files, graph, docs, chat)
  psql -v ON_ERROR_STOP=1 -q <<SQL
DELETE FROM sessions WHERE expires_at < now() - interval '1 day';
DELETE FROM auth_tokens WHERE kind <> 'recovery' AND coalesce(expires_at, created_at) < now() - interval '1 day';
DELETE FROM rate_limit_events WHERE at < now() - interval '2 days';
SQL
  if [ "$RET" -gt 0 ]; then psql -v ON_ERROR_STOP=1 -q -c "DELETE FROM analysis_jobs WHERE state IN ('READY','FAILED','CANCELLED') AND created_at < now() - interval '$RET days'"; fi
}
if [ "${RUN_ONCE:-0}" = "1" ]; then cycle; exit 0; fi
while true; do cycle || echo "backup cycle failed" >&2; sleep "${BACKUP_INTERVAL_SECONDS:-86400}"; done
