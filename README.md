# Raven — evidence-backed codebase onboarding

Raven analyzes a **public GitHub Python/FastAPI repository at a pinned commit** and gives a new developer an architecture map, an onboarding guide, an engineering-readiness report, change-impact analysis and source-grounded Q&A. Analysis is **static** (Python `ast`): the repository is never imported or executed. Every relationship states how it was established (`verified_static` · `inferred` · `unresolved`) and every claim links to file and line ranges.

![Raven architecture map](docs/images/map-01-architecture.png)

**Stack:** React 18 (JSX) + Vite + plain CSS (the proven Map graph engine is reused from `frontend/js`) · FastAPI · PostgreSQL 16 (state **and** work queue) · SQLAlchemy/Alembic · Python worker · n8n (orchestration) · Anthropic API (optional) · Docker Compose

| | Verified in the latest pass ([details](docs/evaluation/EVALUATION_AND_RESULTS.md)) |
|---|---|
| Backend tests | **483 passed, 1 skipped** (pytest, real PostgreSQL; run 2026-11-23) |
| Frontend | React app built in Docker and served by the API; light workspace, Map node graph (pan, zoom, fit, minimap), admin console; **6 web + 9 legacy unit tests passed**. The earlier Playwright run predates the redesign and was not repeated |
| Benchmark evaluation | graph routes P/R 1.000/1.000 · import edges P/R 1.000/0.990 · ORM recall 1.000 · readiness rule P/R 1.000/0.941, location P/R 1.000/0.944 · impact modules/routes recall 1.000/1.000 · citation validity 1.000 · retrieval span recall 0.608, hit@5 0.55 — 3 hand-labelled repos, retrieval-only, all gates passed (re-run 2026-11-23) ([details](docs/evaluation/AI_EVALUATION.md)) |
| Frontend tests | **9 passed** (`node --test`, no dependencies) |
| Full stack | Docker Compose up, all health checks 200, **3 workflows active in real n8n 2.43.4** |
| End to end | `fastapi/full-stack-fastapi-template` analyzed to READY in 11.3 s (711 nodes, 1,603 edges, 23 routes) |
| Not yet verified | AI-answer quality and live LLM calls (no API key used), GitHub Actions CI, a real HTTPS domain, real SMTP delivery, load |

## Features
- **Operations (admin console)** — role-based admin screen: users, analyses, failed jobs, LLM spend, audit log and a one-click abuse switch; per-user daily quotas (analyses, questions, tokens, spend) and per-route rate limits; commit-keyed answer cache and question-embedding cache; monitoring dashboard (latency percentiles, error rate, queue and AI health) and a Prometheus endpoint. See [Administration & operations](docs/ADMIN_AND_OPERATIONS.md).
- **Codebase intelligence** — interactive file-level Map with role filters and folder focus, per-route trace, syntax-highlighted source viewer, and a 16-section onboarding guide with commit-pinned citations.
- **Engineering readiness** — findings on testing, error handling, security, configuration, logging and maintainability, with independent **severity** and **confidence**, a recommendation and how to verify. Evidence is mandatory; security findings are never presented as confirmed.
- **Source-grounded Q&A** — answers cite retrieved code; citations are validated; a rule-based confidence label; claims beyond the code are shown separately as *inferred*; without an LLM, a clearly labelled retrieval-only answer.
- **Change impact** — compare any branch, tag or SHA (default: parent commit) with the analyzed commit: changed files, dependent modules, affected routes, potentially relevant tests, frontend callers.

| Look inside any part | Understand a pull request | Sign in |
|---|---|---|
| ![Files in a group](docs/images/map-02-files-detail.png) | ![Review priority](docs/images/pr-01-review.png) | ![Sign in](docs/images/app-03-signin.png) |

*Screenshots are from a real local run against a public FastAPI repository. The first image is the architecture map; click any block to see the groups and files inside it.*

## Architecture
```mermaid
flowchart LR
  U["Browser<br/>React SPA"] -->|"HTTPS · cookie + CSRF"| API["API · FastAPI<br/>auth · ownership · state machine<br/>Q&A · impact"]
  API --> DB[("PostgreSQL<br/>state + task queue")]
  W["Worker<br/>fetch · parse · graph · docs"] -->|"SKIP LOCKED leases"| DB
  API -->|"webhook + secret"| N8N["n8n · 3 workflows"]
  N8N -->|"/internal/v1 + secret"| API
  W -->|tarball| GH["GitHub"]
  API -->|"lookup · compare"| GH
  API -.->|"Q&A (optional)"| LLM["Anthropic"]
  W -.->|"docs (optional)"| LLM
```
The backend owns every state transition; n8n only sequences, polls, retries and times out, and holds no credentials.

**What happens to a repository**
```mermaid
flowchart LR
  A[Paste URL] --> B["Validate · pin commit"] --> C["Fetch (capped, no code executed)"] --> D["Parse (tolerant, exact lines)"]
  D --> E["Graph + evidence"] --> F["Readiness findings"] --> G["Guide"] --> H["Map · Health · Impact · Ask"]
```
**How an answer is made**
```mermaid
flowchart LR
  Q[Question] --> R["Deterministic retrieval"] --> L{"LLM available?"}
  L -- yes --> M["Cited answer + inferred claims"] --> V["Citations validated"] --> C["Confidence by rule"]
  L -- no --> F["Retrieval-only: source locations"]
```
Sequence diagrams, the state machine, auth/2FA flow, deployment topology and API surface: **[Architecture & Workflows](docs/architecture/ARCHITECTURE_AND_WORKFLOWS.md)**.

## Accounts and security features
Email verification (`REQUIRE_EMAIL_VERIFICATION=true` + SMTP), password reset by emailed single-use link, and TOTP two-factor with recovery codes (Security page). Only token digests are stored; reset revokes every session; 2FA codes cannot be replayed. See [SECURITY.md](docs/SECURITY.md).

## Quick start (Docker Compose)
```bash
cp .env.example .env
./scripts/generate-secrets.sh          # paste the 5 printed values into .env
# optional: set LLM_API_KEY (and LLM_MODEL) for AI explanations and answers; GITHUB_TOKEN raises the GitHub rate limit
docker compose up -d --build
docker compose ps                      # migrate exited 0; api, postgres, n8n healthy; worker up
curl -s localhost:8000/health/ready    # {"status":"ready",...}
open http://localhost:8000
```
Register, paste a public GitHub URL and watch the pipeline. To use the admin console, promote your account: `docker exec -w /app/backend raven-api-1 python -m app.admin_cli grant you@example.com`, then open `#/admin`. The n8n workflows are imported and activated automatically; `curl -X POST localhost:5678/webhook/raven-analysis` should return `401`.

Notes:
- Compose runs in production mode, which requires `COOKIE_SECURE=true`. Chrome accepts secure cookies on `http://localhost` (verified); use HTTPS for any other host — see [DEPLOYMENT.md](docs/DEPLOYMENT.md).
- Without an LLM key, everything except AI prose works: the guide is marked *partial* and Q&A is retrieval-only. Raven never fabricates AI output.
- Unauthenticated GitHub access allows 60 requests/hour.

### Key configuration
| Variable | Notes |
|---|---|
| `POSTGRES_PASSWORD`, `APP_SECRET_KEY`, `INTERNAL_SERVICE_SECRET`, `N8N_WEBHOOK_SECRET`, `N8N_ENCRYPTION_KEY` | required; ≥32 chars, distinct (production refuses to start otherwise) |
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` | optional; provider `anthropic` |
| `GITHUB_TOKEN` | optional; no scopes needed (public data only) |
| `MAX_*`, `ANALYSES_PER_HOUR`, `CHAT_PER_MINUTE`, `DAILY_*`, `RL_*`, `ANSWER_CACHE_*` | analysis limits, quotas, rate limits, caching; every variable is listed in [CONFIGURATION.md](docs/CONFIGURATION.md) |

## Deploying (HTTPS, backups, monitoring)
```bash
docker compose --profile proxy --profile backup --profile monitor up -d    # Caddy (automatic HTTPS, blocks /internal/), daily pg_dump + housekeeping, webhook alerts
```
Set `RAVEN_DOMAIN`, `ALERT_WEBHOOK_URL`, SMTP and `REQUIRE_EMAIL_VERIFICATION` in `.env`. Details, restore steps and what is not verified: [DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Local development without Docker
```bash
python3.12 -m venv .venv && . .venv/bin/activate && pip install -r backend/requirements-dev.txt
createdb raven && export DATABASE_URL=postgresql://user:pass@localhost/raven
cd backend && alembic upgrade head
uvicorn app.main:app --reload &        # http://localhost:8000 (serves ../frontend)
python -m app.workers.main &           # worker
(cd web && npm install && npm run dev)  # React dev server on :5173, proxies /api to :8000; `npm run build` for dist (served via WEB_DIST_DIR). The previous vanilla UI stays at /legacy.
# n8n 2.x (Node >= 24) with the env vars from docs/N8N.md, then import automation/n8n/*.json
```

## Tests
```bash
cd backend && TEST_DATABASE_URL=postgresql://user:pass@localhost/raven_test python -m pytest -q   # use a dedicated database: the suite drops its schema
ruff check backend/app backend/tests backend/evals
node --test frontend/tests/*.test.mjs
(cd web && npm test)                                   # React shell checks: routing, @legacy imports, API endpoints exist, no raw HTML
python automation/n8n/build_workflows.py && git diff --exit-code automation/n8n                  # workflows in sync
cd backend && EVAL_DATABASE_URL=postgresql://user:pass@localhost/raven_eval python -m evals run --suite smoke   # benchmark evaluation (no LLM, no network); see docs/evaluation/AI_EVALUATION.md
bash e2e/up.sh && python3 e2e/browser_ui_basic.py && python3 e2e/browser_full_flow.py           # Playwright suite (Linux paths; not re-run in the latest pass)
```

## Documentation
| Document | Purpose |
|---|---|
| [Product](docs/product/PRODUCT.md) | problem, capabilities, user journey, scope |
| [Architecture & Workflows](docs/architecture/ARCHITECTURE_AND_WORKFLOWS.md) | components, diagrams, workflows, API, security |
| [Evaluation & Results](docs/evaluation/EVALUATION_AND_RESULTS.md) | verified results, untested capabilities, limitations, roadmap |
| [Sprints](docs/sprints/SPRINTS.md) | delivery history, what each sprint proved, defects found, next sprints |
| [Testing log](docs/testing/TESTING_LOG.md) | test strategy, latest results, test map, defects found by testing |
| [AI Evaluation](docs/evaluation/AI_EVALUATION.md) | evaluation framework, benchmark, metric definitions, scores and the defects they found |
| [Administration & operations](docs/ADMIN_AND_OPERATIONS.md) | admin role, abuse switch, quotas, rate limits, caching, monitoring |
| [API reference](docs/API.md) | every route, authentication level, limits |
| [Configuration](docs/CONFIGURATION.md) | every environment variable with its default |
| [Portfolio guide](docs/PORTFOLIO.md) | pitch, resume bullets with measured numbers, demo script, honest gaps |
| [docs/README.md](docs/README.md) | index of all reference docs (security, n8n, deployment, testing log, limitations) |

## Repository layout
```
backend/app/{api,analysis,services,retrieval,workers,models,schemas,core}   (api/routes_admin.py, services/quotas.py, core/metrics.py: operations)   backend/migrations/   backend/tests/
backend/evals/          evaluation harness + versioned benchmark (not part of the runtime image)
web/                   React app (Vite, JSX, plain CSS), built into the API image
frontend/{index.html,js,css,assets}   frontend/tests/   legacy UI at /legacy; js/ also supplies the graph engine and helpers to web/
automation/n8n/        workflow JSON + generator (build_workflows.py)
infra/                 Dockerfile, n8n entrypoint
docs/                  product/, architecture/, evaluation/, images/, reference docs
e2e/  scripts/  docker-compose.yml  .env.example
```

## Limitations
Static analysis only (dynamic imports, DI and runtime-generated routes can be missed) · Python/FastAPI and public GitHub repositories only · parser runs on Python 3.12 · best-effort secret redaction · lexical retrieval · no email verification/password reset/MFA. Full list: [LIMITATIONS.md](docs/LIMITATIONS.md).

Third-party assets (Mermaid, Inter, JetBrains Mono) and their licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The repository does not include a license file for Raven itself.
