# Configuration reference

Every setting is an environment variable, validated at start-up by `backend/app/core/config.py` (the single source of truth; this table is generated from it). Compose reads them from `.env` (start from `.env.example`). In production (`APP_ENV=production`) the API refuses to start with missing, short, placeholder or duplicate secrets, insecure cookies or a non-official GitHub host. Secret values are never printed in errors or logs.

Values shown as `24 * 14` or `300_000` are Python expressions in the source; set plain integers in `.env`.

**General**

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` |  |
| `APP_SECRET_KEY` | `(unset)` |  |
| `DATABASE_URL` | `""` |  |
| `LOG_LEVEL` | `INFO` |  |

**LLM provider (single provider initially: anthropic)**

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` |  |
| `LLM_API_KEY` | `(unset)` |  |
| `LLM_MODEL` | `""` |  |
| `LLM_BASE_URL` | `https://api.anthropic.com` |  |
| `LLM_TIMEOUT_SECONDS` | `60.0` |  |
| `LLM_MAX_RETRIES` | `2` |  |
| `LLM_MAX_OUTPUT_TOKENS` | `2000` |  |
| `LLM_MAX_CONCURRENCY` | `4` | simultaneous in-flight provider calls per process |
| `LLM_MAX_RETRY_AFTER_SECONDS` | `20.0` | a longer Retry-After is not waited out; fail fast to retrieval-only/fallback |
| `LLM_PRICE_INPUT_PER_MTOK` | `None` | optional USD list prices; cost is reported only when both are set |
| `LLM_PRICE_OUTPUT_PER_MTOK` | `None` |  |
| `LLM_MAX_TOKENS_PER_REQUEST` | `60000` | input+output budget for one Q&A/analysis request |

**Optional fallback model, tried when the primary fails with an availability error (provider**

| Variable | Default | Notes |
|---|---|---|
| `LLM_FALLBACK_PROVIDER` | `""` |  |
| `LLM_FALLBACK_MODEL` | `""` |  |
| `LLM_FALLBACK_API_KEY` | `(unset)` |  |
| `LLM_FALLBACK_BASE_URL` | `""` |  |

**Optional semantic retrieval: any OpenAI-compatible /v1/embeddings endpoint. Unset = lexica**

| Variable | Default | Notes |
|---|---|---|
| `EMBEDDINGS_BASE_URL` | `""` |  |
| `EMBEDDINGS_MODEL` | `""` |  |
| `EMBEDDINGS_API_KEY` | `(unset)` |  |

**GitHub**

| Variable | Default | Notes |
|---|---|---|
| `GITHUB_API_BASE_URL` | `OFFICIAL_GITHUB_API` |  |
| `GITHUB_TOKEN` | `(unset)` | optional; raises the unauthenticated rate limit |
| `GITHUB_CONNECT_TIMEOUT` | `5.0` |  |
| `GITHUB_READ_TIMEOUT` | `20.0` |  |
| `MAX_ARCHIVE_BYTES` | `60 * 1024 * 1024` | compressed bytes streamed per analysis |
| `MAX_ARCHIVE_UNCOMPRESSED_BYTES` | `400 * 1024 * 1024` |  |

**Orchestration**

| Variable | Default | Notes |
|---|---|---|
| `N8N_BASE_URL` | `""` |  |
| `N8N_ENCRYPTION_KEY` | `""` | consumed by the n8n container; validated here for prod |
| `N8N_WEBHOOK_SECRET` | `(unset)` | app -> n8n |
| `INTERNAL_SERVICE_SECRET` | `(unset)` | n8n -> app |
| `N8N_TRIGGER_TIMEOUT_SECONDS` | `10.0` |  |
| `QA_WORKFLOW_TIMEOUT_SECONDS` | `120.0` |  |
| `TRIGGER_MAX_ATTEMPTS` | `5` |  |

**Resource limits (spec section 7 defaults)**

| Variable | Default | Notes |
|---|---|---|
| `MAX_REPOSITORY_FILES` | `2000` |  |
| `MAX_SOURCE_FILE_BYTES` | `1024 * 1024` |  |
| `MAX_TOTAL_SOURCE_BYTES` | `20 * 1024 * 1024` |  |
| `MAX_PYTHON_FILES` | `1000` |  |
| `MAX_WEB_FILES` | `300` |  |
| `MAX_WEB_FILE_BYTES` | `256 * 1024` |  |
| `MAX_WEB_TOTAL_BYTES` | `5 * 1024 * 1024` |  |
| `MAX_LLM_LINES_PER_REQUEST` | `1200` |  |
| `MAX_LLM_CALLS_PER_ANALYSIS` | `80` |  |
| `MAX_ANALYSIS_SECONDS` | `600` |  |
| `MAX_DOCS_SECONDS` | `600` |  |
| `IMPACT_PER_HOUR` | `10` |  |
| `MAX_CONCURRENT_ANALYSES` | `2` |  |

**Retry policy**

| Variable | Default | Notes |
|---|---|---|
| `MAX_STAGE_ATTEMPTS` | `3` |  |
| `RETRY_BASE_SECONDS` | `5.0` |  |
| `RETRY_MAX_SECONDS` | `120.0` |  |

**Auth / sessions / rate limits**

| Variable | Default | Notes |
|---|---|---|
| `WEB_DIST_DIR` | `None` | built React app (web/dist); when set, it is served at / and the legacy UI moves to /legacy |
| `ALLOW_REGISTRATION` | `True` |  |
| `REQUIRE_EMAIL_VERIFICATION` | `False` | recommended for public sign-ups; needs SMTP_HOST in production |
| `APP_BASE_URL` | `http://localhost:8000` | used in emailed links |
| `SMTP_HOST` | `None` |  |
| `SMTP_PORT` | `587` |  |
| `SMTP_USER` | `None` |  |
| `SMTP_PASSWORD` | `(secret)` |  |
| `SMTP_FROM` | `Raven <no-reply@localhost>` |  |
| `SMTP_STARTTLS` | `True` |  |
| `EMAIL_TOKEN_TTL_MINUTES` | `60` |  |
| `SESSION_TTL_HOURS` | `24` |  |
| `COOKIE_SECURE` | `None` | default: True in production |
| `LOGIN_MAX_ATTEMPTS` | `10` |  |
| `LOGIN_WINDOW_SECONDS` | `900` |  |
| `ANALYSES_PER_HOUR` | `20` |  |
| `CHAT_PER_MINUTE` | `20` |  |
| `MAX_REQUEST_BYTES` | `64 * 1024` |  |
| `ANSWER_CACHE_ENABLED` | `True` |  |
| `ANSWER_CACHE_TTL_HOURS` | `24 * 14` | entries are exact for their commit; the TTL only bounds table growth |

**Per-user daily quotas (UTC day) and per-endpoint rate limits; a per-user override on the u**

| Variable | Default | Notes |
|---|---|---|
| `DAILY_ANALYSES` | `30` |  |
| `DAILY_QUESTIONS` | `100` |  |
| `DAILY_LLM_TOKENS` | `300_000` |  |
| `DAILY_SPEND_USD` | `None` | also enforced when set and both LLM prices are configured |
| `RL_READ_PER_MINUTE` | `240` | GET endpoints, per user and route |
| `RL_WRITE_PER_MINUTE` | `30` | POST/PUT/PATCH/DELETE endpoints, per user and route |

**Database pool**

| Variable | Default | Notes |
|---|---|---|
| `DB_POOL_SIZE` | `5` |  |
| `DB_MAX_OVERFLOW` | `5` |  |

**Worker / static frontend**

| Variable | Default | Notes |
|---|---|---|
| `WORKER_POLL_SECONDS` | `1.0` |  |
| `WORKER_LEASE_SECONDS` | `60` |  |
| `WORKER_SHUTDOWN_GRACE_SECONDS` | `30` |  |
| `FRONTEND_DIR` | `""` |  |

**Testing hook: allow non-official GitHub host outside production only**

| Variable | Default | Notes |
|---|---|---|
| `ALLOW_CUSTOM_UPSTREAMS` | `False` |  |
