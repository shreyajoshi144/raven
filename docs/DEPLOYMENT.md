# Deployment

## Docker Compose (recommended)
```bash
cp .env.example .env
./scripts/generate-secrets.sh        # prints POSTGRES_PASSWORD, APP_SECRET_KEY, INTERNAL_SERVICE_SECRET, N8N_WEBHOOK_SECRET, N8N_ENCRYPTION_KEY
# paste those values into .env; set LLM_API_KEY / LLM_MODEL if you want AI explanations and answers
docker compose up -d --build
docker compose ps                    # postgres, api, worker, n8n healthy; migrate exited 0
curl -s localhost:8000/health/ready  # {"status":"ready",...}
```
Open http://localhost:8000 (the React app; the previous UI remains at /legacy). Compose runs with `APP_ENV=production`, which rejects `COOKIE_SECURE=false`; Chrome accepts secure cookies on `http://localhost` (verified), and any other host must be served over HTTPS.

## After the first start
Promote your account to administrator and set usage limits: see [ADMIN_AND_OPERATIONS.md](ADMIN_AND_OPERATIONS.md). Take a `pg_dump` before upgrading: migrations 0007 and 0008 add columns and tables only. Settings for quotas and caching are in [CONFIGURATION.md](CONFIGURATION.md).

## Optional profiles (verified on Docker Desktop for Mac only)
| Profile | Service | What it does | Verified |
|---|---|---|---|
| `proxy` | Caddy | Automatic HTTPS for `RAVEN_DOMAIN`; returns 404 for `/internal/*`, `/api/docs`, `/docs`, OpenAPI JSON; HSTS | `caddy validate` passes. **No certificate has been issued**: needs a public domain and ports 80/443 |
| `backup` | postgres:16-alpine | Daily `pg_dump -Fc` to the `backups` volume, keeps `BACKUP_KEEP_DAYS` (14), deletes expired sessions/auth tokens/old rate-limit rows, optional `ANALYSIS_RETENTION_DAYS` | Ran against PostgreSQL 16: dump created, **restore into a fresh database matched row counts**, housekeeping deleted old rows |
| `monitor` | curl | Polls `/health/ready` and `/health/orchestrator`; posts `{"text": ...}` to `ALERT_WEBHOOK_URL` after 2 consecutive failures, once per outage | Logic tested with a stubbed `curl` (alert once, no repeats); **the recovery message and real webhooks were not exercised** |

Restore: `docker compose exec -T postgres sh -c 'createdb -U raven raven_restore'`, then `docker compose cp <dump> postgres:/tmp/r.dump` and `docker compose exec postgres pg_restore -U raven -d raven_restore /tmp/r.dump`. Copy the `backups` volume off the host as well; a backup on the same disk is not a backup.

Email: set `SMTP_HOST` (+ port/user/password/from) and `APP_BASE_URL` (the public https URL). With `REQUIRE_EMAIL_VERIFICATION=true` production refuses to start without `SMTP_HOST`. Real SMTP delivery has **not** been tested; without SMTP, development logs the message and production sends nothing.

Linux: the images are Linux containers and were built and run under Docker Desktop's Linux VM; a native Linux host has not been tested. Build from a path without unusual characters (a folder name containing U+202F made `docker build` fail with a gRPC header error).

Existing databases: migration `0003` adds the account columns and marks all existing users as email-verified, so enabling verification does not lock anyone out.

## Production notes
* Put a TLS reverse proxy in front of `api` (port 8000). **Block `/internal/`, `/api/docs` and the n8n port** at the proxy; the n8n editor is bound to 127.0.0.1 — reach it through an SSH tunnel.
* Caddy example:
  ```
  raven.example.com {
      @internal path /internal/*
      respond @internal 404
      reverse_proxy 127.0.0.1:8000
  }
  ```
* Back up the `pgdata` volume (all application state) and `n8ndata` (n8n encryption/config; workflows are re-importable from git).
* Scale: run more `worker` replicas (`docker compose up -d --scale worker=3`); the queue uses row locks and leases so workers never double-claim. Tune `MAX_CONCURRENT_ANALYSES` per worker.
* Upgrades: `docker compose build && docker compose up -d` — the `migrate` service runs Alembic first. Roll back a bad migration with `docker compose run --rm migrate alembic downgrade -1`.
* Logs are JSON on stdout (`docker compose logs -f api worker`), correlated by `request_id`, `analysis_id`, `workflow`, `execution_id`.
* Health: `/health/live`, `/health/ready` (DB + migrations), `/health/orchestrator` (n8n, separate on purpose), authenticated `/api/v1/status` for provider/limit info.

## Without Docker
See README "Local development without Docker".
