# Changelog

## Unreleased — Map and plain-language pull requests (2026-11)
- **Map** (replaces the first view of the old graph): architecture first (Frontend, API & routes, Business logic, Data & models, Background jobs, Config, Shared code, Scripts & tooling, Tests, External packages), then the groups inside an area, then the files with what each depends on and what uses it. `GET /api/v1/analyses/{id}/map`. The old all-files graph is kept as "Detailed file graph".
- **Canvas navigation**: scroll now moves the canvas; zoom is ⌘/Ctrl + scroll, a trackpad pinch or the +/- buttons. Connection labels only show when few connections are visible.
- **Pull-request review** rewritten for first-time users: review priority with plain reasons, what the PR does, changes grouped by architecture area, "Things to check" with why each matters and whether it is proven or a guess, what else it could affect. Old reviews upgrade themselves on first open.
- **Fewer false alarms**: removed or renamed tests are no longer "breaking public API"; a removed function is only high priority when other code still mentions it; new import cycles are medium.
- "Atlas" is no longer used in the product, docs or URLs (`#/a/{id}/atlas` still redirects to the Map).

## Unreleased — Operations and launch hardening (2026-11)
- **Admin**: `users.role`, `disabled_at`/`disabled_reason`, per-user quota overrides, `admin_events` audit table (migration 0007). `/api/v1/admin/{overview,users,analyses,failures,spend,audit,monitoring}`, disable/enable and quota endpoints, `python -m app.admin_cli grant|revoke`, Admin screen. Disabled accounts cannot sign in; sessions are revoked.
- **Quotas and rate limits**: daily analyses/questions/tokens/spend per user (`DAILY_*`), per-route read/write limits on all session routes (`RL_*`); `QUOTA_EXCEEDED` and `ACCOUNT_DISABLED` error codes.
- **Caching**: commit-keyed answer cache and question-embedding cache, `chat_messages.cache_hit` (migration 0008), hit-rate and savings on the Overview tab, `ANSWER_CACHE_*` settings.
- **Monitoring**: in-process HTTP metrics, Monitoring tab, `GET /internal/v1/metrics` (Prometheus text).
- **Security headers**: added `Cross-Origin-Resource-Policy`, `X-Permitted-Cross-Domain-Policies`, `frame-src/worker-src/manifest-src` CSP directives and a stricter Permissions-Policy.
- **UI**: light redesign (landing, simple auth, route-focused Map workspace).
- **Fix**: idempotency receipts are now namespaced by analysis id (a reused n8n execution id replayed another analysis's receipt and stalled dispatch).
- Backend tests: 483 passed, 1 skipped.

## Unreleased — Sprint 3 (PR intelligence and evaluation)
- `POST/GET /api/v1/pr-reviews[/{id}[/markdown]]`, Pull requests page, `GET /analyses/{id}/usage`, `python -m evals pr`. Migration 0006; optional `LLM_PRICE_*`.

## Unreleased — Sprint 2 (architecture intelligence)
- Architecture snapshot, drift (new deps, cycles, boundary violations, coupling, complexity, breaking changes), history and predicted impact: `GET /analyses/{id}/architecture[/history|/drift]`, new Architecture tab. No migration.

## Unreleased — Sprint 1 (intelligence foundation)
- Retrieval channels (`lexical`/`semantic`/`graph`) with `symbol` and `commit_sha` provenance; `commit_sha` on answers, citations and findings (migration 0005).
- Incremental indexing against the owner's previous analysis (added/modified/deleted/renamed diff, parse and embedding reuse); `POST /analyses/{id}/reindex` for full rebuild.
- Tenant-isolation, failure-consistency and no-LLM tests. See docs/sprints/UPGRADE_PLAN.md.

## AI hardening: fallback model, semantic retrieval, versioning, injection suite (2026-11-01)
- **Second provider + fallback:** `OpenAICompatProvider` (OpenAI-compatible `/v1/chat/completions`: OpenAI, vLLM, Ollama, LiteLLM) and `FallbackProvider`. With `LLM_FALLBACK_*` set, availability errors (503, 429, timeout, 401) on the primary fall back to the second model; bad output does not (the repair loop owns that). The answering model is recorded.
- **Semantic retrieval (optional):** `EMBEDDINGS_*` (any OpenAI-compatible `/v1/embeddings`). Nodes are embedded after the graph stage (failures never fail an analysis); questions are matched by cosine similarity and merged below exact matches, labelled "related to…" so confidence never treats them as direct evidence. Unset = lexical only. Vectors live in `code_nodes.embedding` (deferred JSONB).
- **Versioning:** every AI answer stores `model` and `prompt_version` (content hash of the prompt); shown in the Ask badge tooltip and in the API. Migration `0004`.
- **Prompt-injection suite:** `python -m evals injection` runs a hostile repository (planted instructions in README, docstring, comment, config) through the real answer path; an answer fails on any forbidden string or invalid citation, and a control question catches over-refusal. Separate from benchmark v1, whose fingerprint is unchanged.
- **Tests:** +25 (`test_llm_fallback`, `test_embeddings_retrieval`, `test_injection`). Benchmark smoke still 22/22 and deterministic.
- **Not verified:** none of these four has run against a real model or embeddings endpoint.

## Public sign-up readiness, React frontend, deploy profiles (2026-11-01)
- **Accounts** (migration `0003`; stdlib only, no new backend dependency):
  - email verification: `POST /auth/verify-email`, `/auth/resend-verification`, enforced when `REQUIRE_EMAIL_VERIFICATION=true`;
  - password reset: `POST /auth/forgot-password`, `/auth/reset-password` (revokes all sessions);
  - TOTP two-factor: `POST /auth/2fa/setup`, `/auth/2fa/enable`, `/auth/2fa/disable`, `/auth/login/2fa`, with recovery codes;
  - `/me` now reports `email_verified` and `totp_enabled`;
  - existing users are grandfathered as verified.
- **React frontend** (`web/`: React 18, JSX, Vite, plain CSS; only `react` and `react-dom` as dependencies): new "evidence ledger" identity and screens for auth, account security, dashboard, Overview, Map, Files, Guide, Health, Impact, Ask and System. Reuses, without rewriting, the graph engine (`frontend/js/flow.js`), API client, markdown/mermaid/highlight helpers and `insights.js`. Built in a Docker stage and served at `/`; the previous UI stays at `/legacy`.
- **Deploy profiles**: Caddy HTTPS proxy, daily backup with housekeeping and retention, webhook health monitor.
- **Fixed during verification**: compose required `RAVEN_DOMAIN` even with the proxy profile off; backup housekeeping used wrong table/column names.
- **Tests**: `test_accounts.py` (15), a React-serving test, `web/tests/shell.test.mjs` (5); a full-stack browser run (details in EVALUATION_AND_RESULTS.md).

## SEC-UNAUTH-MUTATION auth recognition (2026-11-01)
- **Alias auth**: the parser records module-level `Name = Annotated[..., Depends(f)]` aliases (`dep_aliases`) and each handler's annotation names (`handler_annotations`). The graph resolves those names, locally or through imports, into the route's dependencies. Routes protected by `current_user: CurrentUser` now count as authenticated, and also gain `uses_dependency` edges.
- **Superuser auth**: the auth-name pattern now includes `superuser`, so `Depends(get_current_active_superuser)` counts.
- **Tests**: 2 regression tests in `tests/test_defect_fixes.py` (one failed before the fix; the other guards that a plain alias without `Depends` adds nothing). Smoke pins updated; 4 floors raised, none lowered.
- **Results**: run `ef5411364870` → `50744a933fd3`.
  - Readiness location precision 0.667→1.000 and recall 0.889→0.944. The 8 protected routes are no longer flagged, and the unprotected `/private/users/` is now reported.
  - Retrieval MRR 0.353→0.366, hit@5 0.500→0.550.
  - **22/22 gates.**

## Defect fixes found by the evaluation benchmark (2026-10-27)
- **Parser compatibility** (`pyparse.parse_tolerant`): a `SyntaxError` no longer discards a whole file.
  - PEP 758 `except A, B:` (Python 3.14) is read as `except (A, B):`.
  - Any other unparseable top-level statement is blanked, and the rest is analysed with unchanged line numbers.
  - Recoveries are reported in `facts.parse_issues`, `parse_warning`, `summary.parse.partial` / `compat_rewrite`, graph gap `partial_parse`, and `MAINT-PARSE-FAILURES` evidence.
  - A file with nothing parseable is still a parse failure.
- **Deterministic retrieval**: content-derived tie-breakers (path, line, `node_key`/`edge_key`) on every limited or order-sensitive query in `app/retrieval/search.py`. Empty files no longer yield "lines 0–0" evidence.
- **SQLModel ORM detection**: `table=True` on a class with SQLModel ancestry, including through intermediate bases, is an ORM table.
- **Readiness / counts**: `CFG-REQUIRED-ENV-AT-IMPORT` only for module-level `os.environ[...]`. Line counts no longer count the empty string after a final newline (shared `filters.count_lines`).
- **Evaluation harness**: `reproducibility.repeats_compared` now counts completed runs (it counted distinct outputs).
- **Tests**: `tests/test_defect_fixes.py`, `tests/test_retrieval_determinism.py` (each failed before its fix); smoke pins updated; 11 smoke floors raised, none lowered.
- **Results** (smoke, retrieval-only): run `ab282dbf401f` → `ef5411364870`. ORM recall 0.50→1.00, import recall 0.90→0.99, readiness rule P/R 0.88/0.88→1.00/0.94, impact recall 0.93/0.87→1.00/1.00, retrieval span recall 0.55–0.575→0.608 (now deterministic).
  - **Readiness location precision fell 0.857→0.667**: an exposed, pre-existing `SEC-UNAUTH-MUTATION` gap (still open; its gate fails).

## AI evaluation framework (evaluation only; no change to Raven's APIs, UI, n8n workflows, schema or runtime dependencies)
- **`backend/evals`** (`python -m evals validate | run | report | verify-sources`). It scores Raven's real code paths (`run_analysis_task`, `qa.internal_retrieve` / `internal_answer`, `compute_impact`) against a versioned, hand-labelled benchmark. Deterministic metrics come first; an optional DeepEval LLM judge scores correctness, faithfulness and answer relevancy of AI answers.
  - Outputs: `results.json` + `report.md` with sample counts, failures, baseline deltas and threshold gates.
  - Also measured: latency, tokens, estimated cost (`pricing.json`), errors, and reproducibility across `--repeats`.
  - Missing credentials or a missing DeepEval are reported as `skipped` with the reason; nothing is imputed.
- **Benchmark v1**: two synthetic FastAPI repositories plus the `backend/` of `fastapi/full-stack-fastapi-template` @ `b1125d8` (vendored byte-identical, MIT). Contents:
  - 27 Q&A items (7 unanswerable), 30 routes, 25 data models, 100 import edges;
  - readiness labels for 20–25 rules per repo;
  - 5 change-impact scenarios.
  - Every evidence span is anchor-checked and every source tree is content-hashed.
- **Tests and CI.**
  - `tests/test_evals_units.py`, `tests/test_evals_smoke.py` (smoke regression with known defects pinned), `tests/test_evals_deepeval.py` (opt-in).
  - CI runs `evals validate` + the hermetic smoke evaluation and uploads the report.
  - `.github/workflows/eval-live.yml` runs live-model evaluation on manual dispatch only.
- **Optional dependency**: `backend/requirements-eval.txt` (deepeval 4.3.1, anthropic 2.3.0) for a separate virtualenv; DeepEval requires `click<8.4`, which conflicts with the runtime pin.
- **Raven defects found by the benchmark (not fixed in this change)**:
  - a Python 3.14-syntax file cascades into lost edges, a false "no auth" finding and missed impact;
  - SQLModel `table=True` via a base class is not classified as ORM;
  - `os.getenv` without a default is flagged "required at import";
  - module line count is off by one;
  - retrieval is non-deterministic (`LIMIT` without tie-breakers).
  - Details: `docs/evaluation/AI_EVALUATION.md` §9.

## UI integration pass (no backend, schema, workflow or contract changes)
- **Health tab** (`view_health.js`): the engineering-readiness report. Severity / minimum-confidence / category / kind filters use the API's own query parameters; severity tiles toggle the severity filter; each finding shows severity, confidence, kind, claim, recommendation, how to verify, the search basis for absence findings, and evidence chips that open the exact lines in the source viewer. Disclaimer, "not assessed" list, partial-analysis warning, empty/filtered-empty/older-analyzer states.
- **Impact tab** (`view_impact.js`): compare a base (parent commit by default, or a branch/tag/SHA) with the analyzed commit; changed files, affected modules (hops, via), affected routes (handler file:line), potentially relevant tests, frontend callers, change-neighbourhood graph, limitations, recent-comparison history. A link-confidence filter (all / verified + inferred / verified only) applies to every link list. API errors (invalid ref, unknown ref, rate limit, GitHub failure) are shown under the form without losing the input.
- **Ask:** confidence badge (with its rule as a tooltip), the source-supported answer and its clickable citations shown apart from a separately styled "Inferred — not shown directly by the cited code" block; retrieval-only answers unchanged (never show inferred claims). Clearing the conversation now reports API errors.
- **Fixed `.env.example`:** `KEY=   # comment` lines are read by Docker Compose as the value `# comment`; for `GITHUB_TOKEN` that sent a bogus token and every analysis failed with `REPO_FORBIDDEN`. Comments now sit on their own lines (regression test in `test_config.py`).
- **Fixed** the Guide's table-of-contents active-section highlight (`data-t` was dropped by `el()`; now `dataset`).
- Workspace tabs and the command palette include Health and Impact; narrow-screen (<=640px) padding/filter-bar adjustments.
- Tests: `frontend/tests/insights.test.mjs` (`node --test`, no dependencies; also run in CI), `backend/tests/test_ui_contracts.py` (the fields these screens read, filter semantics, evidence/impact links resolve to stored files, Q&A confidence/inferred and retrieval-only fallback, CSRF, ownership), `backend/tests/test_workflows.py` (generator in sync, workflow graphs well-formed and fully reachable, secrets only from the n8n environment).

# Production-readiness pass (analyzer 1.1.0, migration 0002)

Additive only. The three n8n workflows, internal API contracts, job state machine, auth and UI structure are unchanged.

## Added
- **Frontend retention and tracing.** `.html .css .js .mjs .ts .tsx .jsx .vue` files are stored (redacted, size-limited, minified/bundled output excluded) and statically scanned as text (nothing is executed): `fetch`, axios-style clients, XHR, jQuery, htmx and `<form>` calls; imports; `<script>`/`<link>`; DOM-injection sinks. Calls are linked to FastAPI routes only when the URL is a literal or a template with placeholders. All such links are labelled **inferred** (a string match, never "verified"); computed/relative URLs and non-matching URLs are **unresolved** with the reason. New `calls_api` edges; Map role `frontend`; route trace shows frontend callers; guide section 15.
- **Engineering-readiness report** (`GET /analyses/{id}/readiness`, guide section 16): testing gaps (import reachability, explicitly *not* coverage), error handling, security/configuration patterns, logging, maintainability. Every finding has severity, confidence, kind (`observed` / `potential_risk` / `absence` / `coverage_gap` / `metric`), recommendation and how to verify. Pattern findings without file:line evidence are dropped; absence findings must state what was searched. Security findings are never "confirmed". Secret values are never included (line numbers only).
- **Change impact** (`POST/GET /analyses/{id}/impact`): GitHub compare (default base = first parent) mapped onto the stored graph: changed files, dependents (reverse imports, depth <= 3), affected routes, potentially relevant tests, frontend callers, mini graph. Strict ref validation; rate-limited; cached (20 per analysis).
- **Q&A:** `confidence` label (high/medium/low, a rule over evidence, not a model probability) and a separate `inferred` list for claims beyond the cited code.
- `docs_explain` wall-clock budget (`MAX_DOCS_SECONDS`, default 600): partial docs instead of an n8n timeout.
- Migration `0002` (verified on a database with existing chat rows, `alembic check`, downgrade/upgrade).

## Fixed
- Files API rejected `kind=web`.
- Hardcoded-secret rule was defeated by our own redaction (value became `[REDACTED]` and was filtered as env-var-like).
- Frontend extractor CPU amplification on hostile input (tens of seconds, now 1.4 s at the 240 KB maximum).
