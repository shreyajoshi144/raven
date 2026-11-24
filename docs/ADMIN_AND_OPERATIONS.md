# Administration, quotas, caching and monitoring

This document covers what an operator needs after Raven is running: who can administer it, how usage is limited, what is cached, and how to watch it. Everything here is implemented and covered by tests (`test_admin_quotas.py`, `test_cache.py`, `test_monitoring.py`, `test_security_api.py`).

## Administrators
Users have a `role` (`user` or `admin`). There is no way to become an administrator through the API; promotion is an operator action on the server:

```bash
docker exec -w /app/backend raven-api-1 python -m app.admin_cli grant you@example.com
docker exec -w /app/backend raven-api-1 python -m app.admin_cli revoke you@example.com
```
Administrators get an **Admin** link in the navigation (`#/admin`). The screen is only a view over the Admin API; every route re-checks the role server-side, and non-admins receive `403 FORBIDDEN`.

| Tab | What it shows |
|---|---|
| Overview | users (new, disabled), analyses in the last 24 h by state, failed jobs, questions, tokens, spend, AI latency, answer-cache hit rate and savings |
| Monitoring | see below |
| Users | search by email; status; today's analyses / questions / tokens against each user's limits; **Quotas**, **Disable / Enable** |
| Analyses | every analysis with owner, repository, commit and state; filter by state |
| Failed jobs | failures with error code, the stage that failed, retryability; counts by code |
| LLM spend | tokens per day and top users over 14 days; dollars when prices are configured |
| Audit log | who did what to whom, and when |

**Abuse switch.** *Disable* stops the user immediately: all their sessions are revoked, sign-in returns `ACCOUNT_DISABLED`, and API calls with an old cookie are refused. *Enable* restores access. You cannot disable yourself or another administrator. Every admin mutation (disable, enable, quota change) is written to the append-only `admin_events` table with the acting admin, the target and the details.

## Quotas and rate limits
Two layers, both per user:

| Layer | Default | Setting | On exceed |
|---|---|---|---|
| Analyses per UTC day (includes PR reviews) | 30 | `DAILY_ANALYSES` | `429 QUOTA_EXCEEDED` |
| Questions per UTC day | 100 | `DAILY_QUESTIONS` | `429 QUOTA_EXCEEDED` |
| AI tokens per UTC day (input + output) | 300 000 | `DAILY_LLM_TOKENS` | `429 QUOTA_EXCEEDED` on the next question |
| AI spend per UTC day | off | `DAILY_SPEND_USD` (needs `LLM_PRICE_INPUT_PER_MTOK` and `LLM_PRICE_OUTPUT_PER_MTOK`) | `429 QUOTA_EXCEEDED` |
| Requests per minute, per route | 240 GET, 30 write | `RL_READ_PER_MINUTE`, `RL_WRITE_PER_MINUTE` | `429 RATE_LIMITED` + `Retry-After` |
| Existing guards | analyses/hour, chat/minute, login attempts, registrations | `ANALYSES_PER_HOUR`, `CHAT_PER_MINUTE`, `LOGIN_MAX_ATTEMPTS` | `429 RATE_LIMITED` |

Daily usage is **derived from the tables that already record it** (analysis jobs; chat messages with their token counts), so there is no second counter to drift. An administrator can override the three daily limits for one user from the Users tab; a blank field means the platform default.

Rate limits: write requests use the shared PostgreSQL limiter (correct across processes). Read requests use a cheap in-process sliding window, so with several API processes the effective read budget is per process.

**Known gaps:** PR-review LLM tokens are not recorded per user, so they do not count toward the token or spend caps (the review still counts as an analysis). Spend is computed from your configured list prices, not from provider invoices.

## Caching
| Cache | Key | Stores | Notes |
|---|---|---|---|
| Answer cache (`answer_cache`) | repository + commit SHA + analyzer version + prompt version + model + normalised question | validated AI answers with citations, confidence and inferred claims | only answers that are model-generated **and** judged `sufficient`; fallbacks and "insufficient" answers are never cached. A commit is immutable, so an entry cannot go stale; a prompt, model or analyzer change changes the key. Shared by all users of the same public repo at the same commit |
| Question embeddings (`embedding_cache`) | embeddings model + normalised text | the vector | only used when `EMBEDDINGS_*` is configured |

A cache hit makes no retrieval or model call, bills no tokens, and is marked `cache_hit` (the Ask screen shows "instant · cached"). Hits still count toward the daily question quota. Controls: `ANSWER_CACHE_ENABLED`, `ANSWER_CACHE_TTL_HOURS` (default 336; bounds table growth only). The Overview tab reports the 24 h hit rate, tokens saved and model calls avoided.

## Monitoring
**Monitoring tab (Admin).** Service health (database, n8n, queue); requests per minute, 5xx rate and p50/p95/p99 latency for the last 5–120 minutes; analyses per day with success rate and p95 duration over 14 days; worker queue by status, age of the oldest pending task and expired leases; AI answers in 24 h split into model / retrieval-only / failed with latency p50/p95; slowest routes.

HTTP figures come from the API process's in-memory per-minute buckets (static files and health probes excluded; route labels collapse ids) and reset on restart; job, queue and AI figures are read from PostgreSQL and are exact.

**Prometheus.** `GET /internal/v1/metrics` returns text-format metrics (`raven_http_requests_total`, `raven_http_errors_total{class}`, `raven_http_latency_p95_ms`, `raven_analysis_jobs{state}`, `raven_worker_tasks{status}`, `raven_process_uptime_seconds`). It needs the `X-Internal-Secret` header and is blocked by the Caddy proxy for public traffic, so scrape it from inside the network.

**Alerts.** The `monitor` Compose profile sends webhook alerts for health failures (see [DEPLOYMENT.md](DEPLOYMENT.md)). There are no threshold alerts on the numbers above yet.

## Backups before schema changes
Migrations 0007 (admin role, quota overrides, audit trail) and 0008 (caches) are additive. Take a dump first, as for any migration:
```bash
docker exec raven-postgres-1 sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > raven-$(date +%Y%m%d-%H%M%S).dump
```
