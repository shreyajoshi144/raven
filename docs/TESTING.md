# Testing — what ran, and what did not

All numbers below are from actual runs in the build environment (Python 3.12, PostgreSQL 16.15, Node 24, headless Chromium via Playwright).

## 1. Backend (pytest, real PostgreSQL, schema created by Alembic)
```
cd backend && TEST_DATABASE_URL=postgresql://raven:***@127.0.0.1:5432/raven_test python -m pytest -q
250 passed
ruff check backend/app backend/tests  →  All checks passed!
```
| File | Tests | Covers |
|---|---:|---|
| test_urls | 37 | canonicalization; rejects look-alike hosts, userinfo, ports, encoding, extra path, unicode homoglyphs, traversal |
| test_secrets_filters | 6 | token/PEM/JWT/URL-password redaction (line numbers preserved), path exclusion rules, binary/generated detection |
| test_archive | 10 | file/size/Python-count limits → *partial*, symlink/hardlink/`../` skipped, compressed cap, **decompression bomb**, corrupt/garbage archives, deadline |
| test_graph | 16 | nested `include_router` path resolution, dynamic/unmounted routes flagged, model classification, edge evidence + resolution, deps/models/calls/tests/config/workers, dynamic imports, parse failures, router-include cycle, parser never executes code, regression for module-level-variable imports |
| test_config | 15 | production validation (missing/short/placeholder/duplicate secrets, cookie, upstream host); errors never echo secret values |
| test_github_llm | 17 | status→error-code classification, rate-limit/private/malformed/timeout, redirect host allowlist, token not forwarded to redirect host, LLM retry/backoff/repair/budget/timeouts |
| test_lifecycle | 15 | full pipeline (via the exact internal calls n8n makes), graph/files/docs/download APIs, **file-flow and route-trace projections (roles, lifted evidence, test hiding, folder focus, ownership)**, docs without LLM = PARTIAL, hallucinated AI output rejected, duplicate submission, **ownership/IDOR on every route**, transient failure → RETRYING → success, retry exhaustion + user retry, non-retryable failures, submit error mapping, delete cascade, cancel, docs regeneration |
| test_security_api | 17 | Argon2id storage, cookies flags, server-side session revocation, login/analysis/chat rate limits, CSRF (missing/wrong/other-user token), cross-origin rejection, security headers/CSP, 64 KiB body cap, error envelope, internal API auth |
| test_internal_contract | 90 | idempotent dispatch, invalid transitions (409), duplicate-callback receipts, fail-code allow-list, malformed payloads, concurrent dispatch (one task), workflow-run recording, **full 9×9 state-transition matrix**, backoff bounds |
| test_chat | 17 | tokenizer, retrieval (symbol/route/FTS/neighbours, bounded), secrets never retrieved, grounded answer + citation validation, hallucinated/out-of-range/uncited citations, no-evidence ⇒ no LLM call, LLM 401/429/503/unconfigured ⇒ retrieval-only, prompt-injection structure, workflow-unavailable, rate limit, foreign message |
| test_recovery_migrations | 9 | expired lease requeue, crash mid-pipeline recovery without duplicate artifacts, WORKER_LOST, unreachable n8n re-trigger → FAILED, docs re-trigger, docs failure, retry reuses cached graph (no GitHub call), **`alembic check` (models == migrations) and full downgrade/upgrade** |

## 2. Browser end-to-end (Playwright/Chromium, live API + worker + PostgreSQL + fake GitHub/LLM servers)
* `e2e/browser_ui_basic.py` — **PASSED**: auth flow, error/validation messages, hostile URLs rejected, queued state, status page, command palette, route protection; vendored fonts verified loaded; no CSP violations or JS errors.
* `e2e/browser_full_flow.py` — **PASSED, 14 checks**: pipeline with **2 injected GitHub 503s** (RETRYING visible) → overview (stats, trust bar, architecture preview flow, timeline) → **Map** (file-flow nodes/edges/minimap, selection lights up the connected path, keyboard traversal with arrow keys, edge click → evidence, role-filter re-layout, search highlight, zoom, folder focus with context nodes) → **route trace** (handler → dependencies → models, per-route switching) → files (syntax-highlighted source, neighbourhood flow, pinned permalink, redaction, `.env` unreachable) → command-palette file search → guide (TOC, 14 sections, Mermaid diagrams, citations → in-app viewer, clean download) → ask (cited answer → source; unanswerable → insufficient evidence) → second user gets 404 everywhere → delete.
* **Design-constraint audit** (`e2e/palette_audit.py`, run on every main screen incl. login, dashboard, overview, Map, route trace, files, guide, chat, status): scans every element's computed text/background/border/outline/shadow colours and SVG fill/stroke and **fails on any saturated colour outside the yellow→green hue band (52°–172°)** — i.e. no blue, violet, red, orange or cream/beige — on any large dark surface, on `backdrop-filter`/blur (glass), or on a non-light page background. It caught and I fixed a golden-yellow (48°) that read as amber.

Orchestrator for these runs was `e2e/workflow_runner.mjs` (an interpreter of the workflow JSON), **not n8n**; see LIMITATIONS.md #1.

## 3. Real-world analysis check
A real GitHub tarball of `fastapi/full-stack-fastapi-template` (via codeload, through the real archive reader → parser → graph builder): 248 entries, 43 Python files, 2 secret files excluded, 23 routes found, 14 models, entry points identified, no limit hit; analysis ≈0.4 s. It exposed two issues that fixtures had hidden: imports of module-level variables were flagged unresolved (**fixed**, regression test added; unresolved imports 27 → 10) and one file using Python 3.14-only syntax (`except A, B:`) cannot be parsed on the 3.12 runtime and is reported as a parse failure. The route prefix `settings.API_V1_STR` is shown honestly as a *partial* path (`/{?settings.API_V1_STR}/items/`).

## 4. UI integration pass (macOS, Python 3.12, PostgreSQL 16 in Docker, Node 26, Docker 29.7.2)
```
cd backend && TEST_DATABASE_URL=… python -m pytest -q        → 347 passed  (baseline before this pass: 320 passed)
ruff check backend/app backend/tests                          → All checks passed!
node --test frontend/tests/*.test.mjs                         → 9 passed
python automation/n8n/build_workflows.py && git diff          → no diff (generated JSON in sync)
docker compose up -d --build                                  → migrate exited 0; api, n8n, postgres healthy; worker up
```
New: `test_ui_contracts.py` (19), `test_workflows.py` (7), one `.env.example` check in `test_config.py`, `frontend/tests/insights.test.mjs` (9).
Live stack: all three workflows imported and active in real n8n 2.43.4, unauthenticated webhook POSTs → 401; `fastapi/full-stack-fastapi-template` analysed to READY via n8n (711 nodes, 1603 edges, 23 routes; docs PARTIAL without an LLM key); readiness, impact (parent and a 60-commit range: 58 files, 14 dependent modules, 23 routes, 9 tests), and Q&A (retrieval-only) via the API and the built-in Chromium browser, including filters, evidence → source-line links, an unknown-ref error and 375 px layout.

## 5. AI evaluation framework pass (2026-10-26; macOS, Python 3.12, PostgreSQL 16 in Docker)
```
cd backend && TEST_DATABASE_URL=… python -m pytest -q          → 373 passed, 1 skipped (the DeepEval-only test)
.venv-eval/bin/python -m pytest -q   (DeepEval 4.3.1 installed) → 374 passed
ruff check backend/app backend/tests backend/evals               → All checks passed!
node --test frontend/tests/*.test.mjs                            → 9 passed
python -m evals validate                                         → 3 repos, 27 questions (7 unanswerable), 30 routes, 100 import edges, 5 impact cases — OK
python -m evals verify-sources                                   → fastapi_template identical to upstream (58 files)
python -m evals run --suite smoke --repeats 3                    → run ab282dbf401f, 22/22 gates passed (docs/evaluation/results/2026-10-26-smoke-retrieval-only/)
```
Checked by running the CLI:
- `--sut live` without `LLM_API_KEY` exits 2 with the reason, before the database is touched;
- a database name without `eval`/`test` is refused;
- a missing `EVAL_DATABASE_URL` exits 2;
- a judge requested without a live system under test is reported `skipped`;
- the judge reports missing keys, a missing model (openai) and unsupported providers.

**Not run:** `--sut live` and the DeepEval judge against real models (no API keys); GitHub Actions.

## 6. Defect-fix pass (2026-10-27; same environment)
```
pytest -q tests/test_defect_fixes.py tests/test_retrieval_determinism.py   before fixes: 9 failed (+1 guard passed); determinism test failed 3/3 runs
                                                                            after fixes: 11 passed
cd backend && TEST_DATABASE_URL=… python -m pytest -q          → 384 passed, 1 failed (test_smoke_meets_committed_floors: readiness.location_level.precision 0.6667 < 0.85), 1 skipped
.venv-eval/bin/python -m pytest -q                               → 385 passed, 1 failed (same test)
ruff check backend/app backend/tests backend/evals               → All checks passed!
node --test frontend/tests/*.test.mjs                            → 9 passed; node --check on all frontend modules OK
python automation/n8n/build_workflows.py && git diff             → no diff
python -m evals validate                                         → OK (fingerprint 774e9bbd2a2b9fb5, unchanged)
python -m evals run --suite smoke --repeats 3                    → run ef5411364870, 21/22 gates, identical outputs across repeats
```
A regression introduced by the line-count fix (empty files yielding evidence for lines 0–0, citation validity 0.966) was caught by the evaluation and fixed, with a test. Live-model and judge evaluation: still not run.

## 7. SEC-UNAUTH-MUTATION fix (2026-11-01; same environment)
```
pytest -q tests/test_defect_fixes.py -k "auth or alias"          before fix: 1 failed (alias dependency missing), 1 guard passed; after: 2 passed
cd backend && TEST_DATABASE_URL=… python -m pytest -q          → 387 passed, 1 skipped (DeepEval-only test)
.venv-eval/bin/python -m pytest -q                               → 388 passed
ruff check backend/app backend/tests backend/evals               → All checks passed!
node --test frontend/tests/*.test.mjs                            → 9 passed; node --check on all frontend modules OK
python automation/n8n/build_workflows.py && git diff             → no diff
python -m evals validate                                         → OK (fingerprint 774e9bbd2a2b9fb5, unchanged)
python -m evals run --suite smoke --repeats 3                    → run 50744a933fd3, 22/22 gates (floors raised), identical outputs across repeats
```
Live-model and judge evaluation: still not run.

## 8. Public sign-up, React frontend and deploy profiles (2026-11-01)
```
cd backend && TEST_DATABASE_URL=… python -m pytest -q          → 403 passed, 1 skipped (includes alembic check + downgrade/upgrade with migration 0003)
cd web && npm test                                               → 5 passed;  npm run build → OK (233 kB JS, 29 kB CSS)
docker compose up -d --build (from a clean path)                 → migrate 0002→0003 on the existing volume, all services healthy; / serves the React app, /legacy the old UI
Playwright/Chrome end-to-end against the stack                   → register → analyze fastapi/full-stack-fastapi-template → Map (84 nodes) → source lines → Guide (16 sections) → Health filter 6→2 → evidence link highlights a line → Impact (unknown ref error, then a real 59-commit compare) → Ask (retrieval-only) → 2FA setup, login with code, login with recovery code → bad verify link, generic forgot-password message; 375 px: no horizontal scroll on any page; only expected 4xx responses
infra: caddy validate OK; backup + restore verified; monitor alert logic verified with a stub
```
Not run: real SMTP delivery, a real certificate/domain, the verification and reset links end to end in the browser (covered by API tests; the pages were checked only for the invalid-link and generic-response cases), native Linux, load.

## 9. AI hardening pass (2026-11-01)
```
cd backend && TEST_DATABASE_URL=… python -m pytest -q          → 428 passed, 1 skipped (+25 new: fallback/provider, embeddings, versioning, injection)
python -m evals run --suite smoke --repeats 3                    → 22/22 gates, no unstable outputs (retrieval unchanged when embeddings are unset)
python -m evals injection                                        → 6 cases, 0 leaks, AI defences NOT exercised (no LLM)
cd web && npm test && npm run build                              → 5 passed, build OK
```
Not run: any of the four features against a real model or embeddings endpoint.

## 10. Not run (earlier passes)
Real n8n; Docker build/Compose; the real Anthropic API; the live GitHub REST endpoints from this environment (unauthenticated quota exhausted — the client classified it correctly as `GITHUB_RATE_LIMITED`); load/performance tests; automated accessibility audit; browsers other than Chromium.
