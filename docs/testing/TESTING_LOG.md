# Raven — testing log

> Related: [Sprints](../sprints/SPRINTS.md) · [Evaluation](../evaluation/EVALUATION_AND_RESULTS.md) · detailed, chronological command output: [../TESTING.md](../TESTING.md)

**Convention:** ✅ executed and observed in the stated pass · 📄 recorded in an earlier pass, not re-run · ⬜ implemented but never run against the real dependency. Nothing is claimed without one of these marks.

## Test strategy
```mermaid
flowchart TB
  L5["Benchmark evaluation (python -m evals)<br/>real pipeline vs hand-labelled ground truth · CI gates"]
  L4["Full-stack browser run (Playwright/Chrome)<br/>Docker Compose + real n8n + real GitHub"]
  L3["API + lifecycle tests (pytest, real PostgreSQL)<br/>n8n contract, ownership, security, migrations"]
  L2["Unit tests<br/>parser, graph, readiness, metrics, TOTP, URL validation"]
  L1["Static checks<br/>ruff · node --check · workflow JSON generated-in-sync · compose/caddy config validation"]
  L1 --> L2 --> L3 --> L4 --> L5
```

## Latest results (2026-11-25)
The full report, with defects, exit criteria and sign-off, is the [QA report](../project/08-QA-REPORT.md). Summary:

| Layer | Command | Result |
|---|---|---|
| Backend, real PostgreSQL | `cd backend && python -m pytest -q` | ✅ **490 passed**, 1 skipped (the opt-in DeepEval test) |
| Lint | `ruff check backend/app backend/tests backend/evals` | ✅ clean (ruff 0.17.6) |
| Legacy frontend modules | `node --test frontend/tests/*.test.mjs` | ✅ 9 passed |
| React shell | `cd web && npm test` · `npm run build` | ✅ 6 passed · build OK |
| n8n workflows | regenerate and `git diff` | ✅ no diff |
| Benchmark | `python -m evals run --suite smoke` | ✅ run `27e096d5db28`: **22/22 gates** |
| Docker image | `docker build -f infra/Dockerfile .` | ✅ built from scratch (exit 0) |
| Local stack | `docker compose up -d` | ✅ api, worker, postgres, n8n healthy; migrations at head (0008) |
| Browser checks | Map (3 levels), pull-request review, sign-in, landing, admin Monitoring | ✅ observed 2026-11-24/25 (manual) |
| GitHub Actions | first run on the public repository | ❌ backend job failed at lint (fixed `1021a57`); green run not yet recorded |
| AI answer quality, live LLM, judge | `--sut live` | ⬜ **not run** (LLM account has no credit) |
| Real SMTP, public HTTPS deployment, load | — | ⬜ not run |

Earlier full-stack Playwright run (2026-11-01, before the redesign): 📄 not re-run.

## Backend test map (490 + 1 opt-in)
| Area | Files (tests) | What is proven |
|---|---|---|
| n8n/internal contract | `test_internal_contract` (91) | idempotent dispatch, duplicate callbacks, full 9×9 state-transition matrix, concurrency |
| Input hardening | `test_urls` (37), `test_archive` (10), `test_secrets_filters` (6) | look-alike hosts, traversal, decompression bomb, symlinks, redaction |
| Analysis | `test_graph` (17), `test_webparse` (21), `test_readiness` (14), `test_frontend_links` (9), `test_defect_fixes` (11) | route resolution, edge evidence, readiness rules, parser recovery with exact lines |
| Retrieval and Q&A | `test_chat` (17), `test_qa_confidence` (2), `test_retrieval_determinism` (2) | citation validation, abstention, LLM failure → retrieval-only, identical ranked evidence |
| Change impact | `test_impact` (24) | hostile refs rejected before any GitHub call, isolation, rate limit |
| API contracts | `test_ui_contracts` (19), `test_lifecycle` (15), `test_github_llm` (17) | fields the UI reads, ownership on every route, retries, provider errors |
| AI layer (2026-11-01) | `test_llm_fallback` (12), `test_embeddings_retrieval` (6), `test_injection` (7) | fallback on availability errors only, second provider, model + prompt version stored, semantic retrieval incl. failure degrading to lexical and determinism, injection defences and scoring |
| Security and accounts | `test_security_api` (18), `test_accounts` (15), `test_config` (16) | Argon2id, CSRF, CSP, rate limits, verification, reset, TOTP RFC vector, production config refusal |
| Operations | `test_recovery_migrations` (9), `test_workflows` (7) | lease expiry, crash recovery, `alembic check`, downgrade/upgrade, workflow graph |
| Upgrade sprints (S8–S10) | `test_sprint1` (9), `test_architecture` (8), `test_pr_review` (8), `test_evals_pr` (3) | commit-aware answers, incremental indexing, tenant isolation, drift findings, PR review |
| Launch hardening (S13) | `test_admin_quotas` (9), `test_cache` (6), `test_monitoring` (6) | admin-only API, abuse switch, quotas, answer/embedding caches, metrics |
| Map and review verdict (S15) | `test_map_and_review` (7) | area classification, grouping, map endpoint, owner-only, verdict levels |
| Evaluation harness | `test_evals_units` (24), `test_evals_smoke` (3), `test_evals_deepeval` (1, opt-in) | metric maths, stale-label detection, judge retry/timeout, floors |

## Full-stack browser run (✅ 2026-11-01)
```mermaid
flowchart LR
  A[Register] --> B[Analyze real repo] --> C[Map: 84 nodes] --> D[Open source line]
  D --> E[Guide: 16 sections] --> F[Health: filter 6 → 2] --> G[Evidence link → highlighted line]
  G --> H[Impact: unknown ref error, then real compare] --> I[Ask: retrieval-only]
  I --> J[2FA setup] --> K[Login with code] --> L[Login with recovery code]
  L --> M[Invalid verify link · generic reset reply] --> N[375 px: no horizontal scroll]
```
Only the two deliberate 4xx responses occurred (unknown branch, invalid verification token).

## Evidence trail by sprint
| Sprint | Backend tests | Notable verification |
|---|---:|---|
| S0 | 250 | Docker-free Playwright flow with fake GitHub/LLM and an n8n interpreter 📄 |
| S1 | 320 | Impact/readiness/Q&A API tests, migration `0002` with downgrade/upgrade 📄 |
| S2 | 347 | ✅ first real-n8n Docker run; 3 defects found and fixed |
| S4 | 373 | ✅ benchmark baseline: 22/22 gates; 5 Raven defects found |
| S5 | 387 | ✅ 22/22 gates after fixes; 1 regression caught by the harness and fixed |
| S6 | 403 (428 after AI hardening) | ✅ full-stack browser run; ✅ backup restore; 3 defects found and fixed |
| S8–S10 | 462 at the S11 validation | ✅ migrations 0005/0006 on the real database |
| S11 | 462 | ✅ local deployment validation; 1 defect found and fixed |
| S12 | 462 | ✅ browser-verified redesign; web tests 6 |
| S13 | 483 | ✅ admin, quotas, caches, monitoring verified in the browser and by tests |
| S15 | 489 | ✅ Map and PR review verified on a real repository |
| S16 | 490 | ✅ from-scratch image build; ❌ first CI run failed at lint, fixed |

## Defects found by testing (all fixed unless noted)
| Found by | Defect | Status |
|---|---|---|
| Real stack run (S2) | `.env.example` inline comment → bogus `GITHUB_TOKEN` → every analysis `REPO_FORBIDDEN` | fixed + test |
| Real stack run (S2) | `el()` helper dropped `data-*` props (guide highlight) | fixed + test |
| Benchmark (S4) | newer-syntax file dropped whole; non-deterministic retrieval; SQLModel ORM; `os.getenv` rule; line count off by one | fixed + tests |
| Benchmark (S5) | empty files produced "lines 0–0" evidence | fixed + test |
| Benchmark (S5) | `SEC-UNAUTH-MUTATION` missed superuser/`Annotated` auth | fixed + test |
| Full-stack run (S6) | Compose required `RAVEN_DOMAIN` with the proxy off | fixed |
| Backup test (S6) | housekeeping SQL used wrong table and column names | fixed |
| Browser run (S6) | logged-in pages overflowed at 375 px | fixed |
| Local deployment validation (S11) | idempotency receipt reused across analyses (n8n reuses execution ids) stalled dispatch about 95 s | fixed + test |
| Review on a real repository (S15) | removed or renamed tests reported as "breaking public API" (high) | fixed + test |
| Review on a real repository (S15) | removed functions nothing used, and new import cycles, rated high | fixed (downgraded) + test |
| Browser run (S15) | helper scripts and load tests classified as "API & routes" | fixed + test |
| Browser run (S16) | tests listed under a file's "Depends on" in the Map | fixed + test |
| GitHub Actions (S16) | lint failure: fixture imported across test modules | fixed (`1021a57`) |
| Open | re-exported name not linked; literal `getenv` fallback not reported as secret default; lexical retrieval | documented in [LIMITATIONS](../LIMITATIONS.md) |

## How to reproduce
```bash
cd backend && TEST_DATABASE_URL=postgresql://user:pass@localhost/raven_test python -m pytest -q     # use a dedicated database
python -m evals validate && EVAL_DATABASE_URL=postgresql://user:pass@localhost/raven_eval python -m evals run --suite smoke --repeats 3
node --test ../frontend/tests/*.test.mjs && (cd ../web && npm test && npm run build)
```
