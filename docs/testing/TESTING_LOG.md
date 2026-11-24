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

## Latest results (2026-11-01)
| Layer | Command | Result |
|---|---|---|
| Backend, runtime environment | `cd backend && python -m pytest -q` (PostgreSQL 16) | ✅ **428 passed**, 1 skipped (the DeepEval-only test) |
| Backend, DeepEval environment | `.venv-eval/bin/python -m pytest -q` | ✅ **404 passed** |
| Lint | `ruff check backend/app backend/tests backend/evals` | ✅ clean |
| Legacy frontend modules | `node --test frontend/tests/*.test.mjs` + `node --check` | ✅ 9 passed |
| React shell | `cd web && npm test` · `npm run build` | ✅ 5 passed · build OK |
| n8n workflows | regenerate and `git diff` | ✅ no diff; all three JSON files valid |
| Benchmark | `python -m evals validate` · `run --suite smoke` | ✅ labels consistent · **22/22 gates** |
| Compose / Caddy | `docker compose config` (default and all profiles) · `caddy validate` | ✅ |
| Full-stack browser run | Playwright on the rebuilt stack | ✅ see below |
| AI answer quality, live LLM, judge | `--sut live` | ⬜ **not run** (no API key) |
| Real SMTP, real certificate/domain, native Linux, load | — | ⬜ not run |

## Backend test map (428 + 1 opt-in)
| Area | Files (tests) | What is proven |
|---|---|---|
| n8n/internal contract | `test_internal_contract` (90) | idempotent dispatch, duplicate callbacks, full 9×9 state-transition matrix, concurrency |
| Input hardening | `test_urls` (37), `test_archive` (10), `test_secrets_filters` (6) | look-alike hosts, traversal, decompression bomb, symlinks, redaction |
| Analysis | `test_graph` (17), `test_webparse` (21), `test_readiness` (14), `test_frontend_links` (9), `test_defect_fixes` (11) | route resolution, edge evidence, readiness rules, parser recovery with exact lines |
| Retrieval and Q&A | `test_chat` (17), `test_qa_confidence` (2), `test_retrieval_determinism` (2) | citation validation, abstention, LLM failure → retrieval-only, identical ranked evidence |
| Change impact | `test_impact` (24) | hostile refs rejected before any GitHub call, isolation, rate limit |
| API contracts | `test_ui_contracts` (19), `test_lifecycle` (15), `test_github_llm` (17) | fields the UI reads, ownership on every route, retries, provider errors |
| AI layer (2026-11-01) | `test_llm_fallback` (12), `test_embeddings_retrieval` (6), `test_injection` (7) | fallback on availability errors only, second provider, model + prompt version stored, semantic retrieval incl. failure degrading to lexical and determinism, injection defences and scoring |
| Security and accounts | `test_security_api` (18), `test_accounts` (15), `test_config` (16) | Argon2id, CSRF, CSP, rate limits, verification, reset, TOTP RFC vector, production config refusal |
| Operations | `test_recovery_migrations` (9), `test_workflows` (7) | lease expiry, crash recovery, `alembic check`, downgrade/upgrade, workflow graph |
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
| S6 | 403 | ✅ full-stack browser run; ✅ backup restore; 3 defects found and fixed |

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
| Open | re-exported name not linked; literal `getenv` fallback not reported as secret default; lexical retrieval | documented in [LIMITATIONS](../LIMITATIONS.md) |

## How to reproduce
```bash
cd backend && TEST_DATABASE_URL=postgresql://user:pass@localhost/raven_test python -m pytest -q     # use a dedicated database
python -m evals validate && EVAL_DATABASE_URL=postgresql://user:pass@localhost/raven_eval python -m evals run --suite smoke --repeats 3
node --test ../frontend/tests/*.test.mjs && (cd ../web && npm test && npm run build)
```
