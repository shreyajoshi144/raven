# Architecture

```
Browser ──HTTPS──▶ API (FastAPI) ──SQL──▶ PostgreSQL  (source of truth: jobs, artifacts, queue)
                     │  ▲                      ▲
        webhook (secret)│  │ /internal/v1 (service secret)
                     ▼  │                      │
                    n8n  (orchestration only)  Worker (python -m app.workers.main)
                                               ├─ GitHub (api + codeload, host-allowlisted)
                                               └─ LLM provider (optional)
```

## Responsibilities
| Component | Owns |
|---|---|
| **API** | auth/sessions, validation, ownership checks, **every job state transition**, read APIs, serving the static frontend |
| **PostgreSQL** | users, analyses, transitions, files, graph, docs, chat, workflow runs, audit log, **work queue** (`worker_tasks`), idempotency receipts, rate-limit events |
| **Worker** | claims queued tasks (`FOR UPDATE SKIP LOCKED` + leases + heartbeats); runs fetch → parse → graph; documentation explain/assemble; crash recovery and n8n re-triggering |
| **n8n** | sequencing, wait/poll loops, bounded retry/backoff, timeouts, failure reporting. Holds **no** business state and **no** GitHub/LLM credentials |

n8n never writes to the database and never talks to GitHub or the LLM. It only calls authenticated internal endpoints, so a missing/stopped n8n can delay work but cannot corrupt it.

## Job state machine (backend-owned)
`QUEUED → FETCHING → PARSING → BUILDING_GRAPH → GENERATING_DOCS → READY`, with `RETRYING` (transient failure), `FAILED`, `CANCELLED`.
Illegal transitions are rejected (HTTP 409) and every legal one is recorded in `analysis_transitions` with actor (`api`/`worker`/`n8n`). `PARSING`/`BUILDING_GRAPH → FETCHING` exists only for crash recovery. `FAILED → QUEUED` is the user retry.

## Workflows (see docs/N8N.md)
1. `raven_repository_analysis` — dispatch → poll → (retry with backend-computed backoff) → `stage-result(graph)` → trigger docs workflow → report failures.
2. `raven_documentation_generation` — dispatch `docs_explain` → poll → dispatch `docs_assemble` → poll → `complete`.
3. `raven_codebase_qa` — synchronous: `qa/retrieve` → `qa/answer` → respond. Retrieval, validation and persistence stay in the backend.

Internal endpoints (all require `X-Internal-Secret`, refuse requests carrying an `Origin` header):
`POST /internal/v1/analysis-jobs/{id}/dispatch | stage-result | complete | fail`, `GET …/status`, `POST /internal/v1/qa/retrieve | answer`.
Dispatch/stage-result/complete/fail accept an `idempotency_key`; duplicates replay the stored response (`callback_receipts`). Worker tasks have unique idempotency keys so a duplicate dispatch can never enqueue duplicate work.

## Analysis pipeline
1. **Submit** — strict URL parse → GitHub repo lookup (must be public) → default-branch HEAD SHA is pinned. Duplicate owner+repo+SHA(+analyzer version) returns the existing job (partial unique index closes races).
2. **Fetch** — one streamed tarball download (`/repos/{o}/{r}/tarball/{sha}`), decompressed with output caps; members are never extracted to disk; symlinks/hardlinks/traversal paths are skipped; limits on file count, per-file size, total source size, Python file count, archive size, wall-clock. Exceeding a limit yields a **partial** analysis with explicit reasons, never a silent truncation.
2b. **Redaction** — secret-like text is replaced before storage; `.env`-style files are excluded (only variable *names* of `.env.example` are kept).
3. **Parse** — Python `ast` only; code is never imported or executed.
4. **Graph** — nodes (repository, directory, file, module, route, function, class, model, configuration, test, external_dependency, worker) and edges (contains, imports, defines, registers_route, calls, uses_model, uses_dependency, configured_by, tested_by, starts_worker). Every edge has evidence (file + lines) and a resolution of `verified_static`, `inferred` or `unresolved`. FastAPI route paths are computed through nested `include_router` chains.
5. **Docs** — deterministic Markdown with 16 sections, every claim cited to a commit-pinned GitHub permalink; AI text only in clearly labelled narrative/explanation fields, validated against the analyzed files.

## Q&A
Retrieval (exact symbol/path/route match, Postgres full-text search, 1-hop graph neighbours) → bounded evidence (≤12 snippets, ≤400 lines) → LLM → **validation** (citations must be in supplied evidence, inside file bounds, and a "sufficient" answer needs ≥1 citation; one repair attempt) → persisted. If the LLM is unavailable the response is explicitly "retrieval only" with source locations.

## Data lifecycle
Deleting an analysis cascades to files, graph, docs, chat, workflow runs, tasks and receipts. Retrieved Q&A evidence is cleared once an answer is stored. Stored source text is limited to Python and a short allow-list of setup files, redacted.

## Operations layer
Admin API and console, per-user quotas and rate limits, the answer and embedding caches, HTTP metrics and the Prometheus endpoint are described in [ADMIN_AND_OPERATIONS.md](ADMIN_AND_OPERATIONS.md). The architecture-first **Map** (`GET /analyses/{id}/map`) groups files into plain-language areas (Frontend, API & routes, Business logic, Data & models, Background jobs, Config, Shared code, Scripts & tooling, Tests, External packages) before showing files.

## Flow views (frontend)
* `GET /analyses/{id}/graph/flow` — file-level map: symbol edges are **lifted** to the files containing them and aggregated per file pair; each connection keeps its relation kinds, evidence lines and a resolution (`verified_static` only if every underlying edge is). Files get a role (entry / routes / services / data models / workers / config / module) and external packages are added as dashed nodes. `focus=<folder or file>` returns that scope plus up to 20 context neighbours; tests are hidden unless requested.
* `GET /analyses/{id}/graph/trace?node_id=` — symbol-level subgraph (depth ≤ 4, ≤ 60 nodes) from a route/function: *handled by* (route → handler), calls, dependencies, models, workers and configuration.
* `frontend/js/flow.js` renders both (the "Detailed file graph"; the default view is the Map). Scrolling pans the canvas; zoom is ⌘/Ctrl + scroll, pinch or the +/- buttons: longest-path layering with cycle breaking, barycenter ordering, bezier edges, animated "packets" along highlighted paths, pan/zoom/pinch, minimap, focus mode, arrow-key traversal.
