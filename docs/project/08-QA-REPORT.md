# Test and QA report

| | |
|---|---|
| Version / date | 1.0 · 2026-11-25 |
| Tester | Shreya Joshi (with an AI coding assistant running the commands) |
| Build under test | Repository at commit `1021a57` (local stack at migration 0008) |
| Related | [PRD](02-PRD.md) · [Traceability matrix](09-TRACEABILITY-MATRIX.md) · [Testing log](../testing/TESTING_LOG.md) · [Evaluation results](../evaluation/EVALUATION_AND_RESULTS.md) |

**Convention.** ✅ executed and observed in this pass · 📄 recorded in an earlier pass, not re-run · ⬜ never run. Nothing is claimed without one of these marks.

## 1. Scope and strategy
Raven is tested at five levels, from cheap to expensive:

| Level | What it proves | Tool |
|---|---|---|
| Static checks | Style and obvious errors; workflows generated in sync; configuration valid | `ruff`, `node --check`, workflow generator and `git diff`, `docker compose config` |
| Unit and API tests | Parsing, graph, readiness, retrieval, validation, security, quotas, caches, metrics, Map and review logic | `pytest` against a real PostgreSQL (schema created by Alembic) |
| Contract tests | The n8n to API contract, state-transition matrix, idempotency, ownership on every route | `pytest` |
| Benchmark evaluation | Accuracy against hand-labelled ground truth, with pass/fail gates | `python -m evals run --suite smoke` |
| Stack and browser checks | The running system end to end on real services | Docker Compose with real n8n; manual browser checks |

**Test data.** GitHub and the LLM are replaced by fakes (mock HTTP transports) in automated tests; n8n is emulated by issuing its exact internal calls. The benchmark uses 3 hand-labelled repositories, one of them the real `fastapi/full-stack-fastapi-template`.

## 2. Environment
macOS (arm64) · Docker Desktop · Python 3.13 for local runs (the runtime image and CI use Python 3.12) · PostgreSQL 16 in a container · n8n 2.43.4 · no successful live model call (the OpenAI-compatible account has no credit).

## 3. Results (2026-11-25)
| Layer | Command | Result |
|---|---|---|
| Backend | `cd backend && python -m pytest -q` | ✅ **490 passed**, 1 skipped (the opt-in DeepEval test) |
| Lint | `ruff check backend/app backend/tests backend/evals` | ✅ clean (ruff 0.17.6) |
| Legacy frontend | `node --test frontend/tests/*.test.mjs` | ✅ 9 passed |
| React shell | `cd web && npm test` and `npm run build` | ✅ 6 passed, build OK |
| Workflows | `python automation/n8n/build_workflows.py`, then `git diff` | ✅ no diff |
| Benchmark | `python -m evals run --suite smoke` | ✅ run `27e096d5db28`, **22 of 22 gates** |
| Image build | `docker build -f infra/Dockerfile .` | ✅ built from scratch (exit 0) |
| Local stack | `docker compose up -d` | ✅ api, worker, postgres, n8n healthy; migrations at head |
| Documentation | `python scripts/check_docs.py` | ✅ links, naming and numbers consistent |
| GitHub Actions | first run on the public repository | ❌ backend job failed at the lint step (DEF-19); fixed in `1021a57`; green run not yet recorded |
| Live AI answers | `--sut live` or the Ask screen | ⬜ not run: no LLM credit |

Backend tests by area are in [EVALUATION_AND_RESULTS §2](../evaluation/EVALUATION_AND_RESULTS.md) and by file in the [testing log](../testing/TESTING_LOG.md).

## 4. Benchmark results (run `27e096d5db28`, retrieval-only system under test)
The system under test is Raven's retrieval-only path, so these measure the graph, readiness, impact, retrieval and citation checks, **not AI answer quality**. Baseline is the first recorded run (2026-10-26).

| Capability | Metric | Baseline | Now | Labelled items |
|---|---|---:|---:|---:|
| Graph | Routes precision / recall | 1.000 / 1.000 | 1.000 / 1.000 | 30 |
| Graph | Import edges precision / recall | 1.000 / 0.900 | 1.000 / 0.990 | 100 |
| Graph | ORM models recall | 0.500 | 1.000 | 4 |
| Readiness | Rule precision / recall | 0.882 / 0.882 | 1.000 / 0.941 | 17 |
| Readiness | Location precision / recall | 0.857 / 0.667 | 1.000 / 0.944 | 18 |
| Impact | Affected modules recall | 0.926 | 1.000 | 27 |
| Impact | Routes recall | 0.868 | 1.000 | 38 |
| Retrieval | Hit at 5 / MRR | 0.450 / 0.307 | 0.550 / 0.366 | 20 |
| Q&A (fallback) | Citation validity | 1.000 | 1.000 | 24 |

Full report: [results/2026-11-25-smoke-current/report.md](../evaluation/results/2026-11-25-smoke-current/report.md). Earlier runs are kept beside it.
**Reading the numbers honestly.** Three repositories and small counts mean these are not general accuracy estimates. Retrieval is the weakest area. Citation faithfulness is 0.148 in the fallback path because it cites few labelled snippets; it is reported, not gated.

## 5. Manual and browser verification
| Date | What was checked | Result |
|---|---|---|
| 2026-11-01 | Full-stack Playwright run: register, analyse, every tab, 2FA setup and login, recovery code, 375 px width | 📄 passed (before the redesign; not re-run) |
| 2026-11-03 | Local deployment validation (S11): migrations 0005 and 0006 on the real database, API readiness, worker, PostgreSQL, n8n, analysis, retrieval-only Ask, Architecture, pull-request review | ✅ passed; one defect found (DEF-14) |
| 2026-11-05 | Redesigned landing, sign-in and node-graph workspace: pan, zoom, fit, reset, selection, panels | ✅ observed |
| 2026-11-07 | Admin Overview, Users and Monitoring; sign-in as admin | ✅ observed |
| 2026-11-24 | Map: three levels, file detail panel, breadcrumbs, on a 280-file repository (127 routes); scroll pans and ⌘/Ctrl + scroll zooms on the detailed graph | ✅ observed; defects DEF-17, DEF-18, DEF-20 found |
| 2026-11-24 | Pull-request review of a real merged pull request (121 changed files): verdict, areas, findings | ✅ observed; earlier version produced DEF-15, DEF-16 |
| 2026-11-25 | Landing page and sign-in screens | ✅ observed |
Browser checks are manual and in Chromium only. Automated browser suites exist in `e2e/` but were not re-run for the redesigned UI (B-10).

## 6. Defect log
Severity is the owner's assessment at the time. "Found by" shows which check caught it; every fix has a regression test unless noted.

| ID | Sprint | Found by | Defect | Sev. | Status |
|---|---|---|---|---|---|
| DEF-01 | S2 | Real-stack run | `.env.example` inline comment became the GitHub token value, so every analysis failed with `REPO_FORBIDDEN` | High | Fixed + test |
| DEF-02 | S2 | Real-stack run | A frontend helper dropped `data-*` attributes (guide highlight broken) | Low | Fixed + test |
| DEF-03 | S2 | Real-stack run | Impact page overflowed on phones | Low | Fixed |
| DEF-04 | S4 | Benchmark | Newer Python syntax dropped a whole file | Medium | Fixed + test |
| DEF-05 | S4 | Benchmark | Retrieval order not deterministic (5 of 27 questions differed between repeats) | Medium | Fixed + test |
| DEF-06 | S4 | Benchmark | SQLModel ORM models misclassified | Low | Fixed + test |
| DEF-07 | S4 | Benchmark | `os.getenv` flagged as "required at import" | Low | Fixed + test |
| DEF-08 | S4 | Benchmark | Line counts one too high | Low | Fixed + test |
| DEF-09 | S5 | Benchmark (regression) | Empty files produced "lines 0–0" evidence | Low | Fixed + test |
| DEF-10 | S5 | Benchmark | Auth recognition missed superuser and `Annotated` alias dependencies | Medium | Fixed + test |
| DEF-11 | S6 | Full-stack run | Compose required `RAVEN_DOMAIN` even with the proxy profile off | Medium | Fixed |
| DEF-12 | S6 | Backup test | Backup housekeeping used wrong table and column names | Medium | Fixed |
| DEF-13 | S6 | Browser run | Logged-in pages overflowed at 375 px | Low | Fixed |
| DEF-14 | S11 | Deployment validation | n8n reuses execution ids, so an idempotency receipt from one analysis was replayed for another and dispatch stalled about 95 s | High | Fixed + test |
| DEF-15 | S15 | Review on a real repository | Removed or renamed tests reported as "breaking public API" (high) | Medium | Fixed + test |
| DEF-16 | S15 | Review on a real repository | Removed functions that nothing used, and new import cycles, rated high | Medium | Fixed (downgraded) + test |
| DEF-17 | S15 | Browser run | Helper scripts and load tests classified as "API & routes" | Low | Fixed + test |
| DEF-18 | S16 | Browser run | Tests listed under a file's "Depends on" in the Map | Low | Fixed + test |
| DEF-19 | S16 | GitHub Actions | Lint failure: a fixture imported across test modules | Low | Fixed (`1021a57`) |
| DEF-20 | S15 | User feedback | Scroll zoomed the canvas instead of moving it, making navigation hard | Medium | Fixed |
| DEF-21 | S15 | User feedback | All-files graph unreadable: 70 files and 321 connections with overlapping labels and edges | High | Fixed by the architecture-first Map (D-11) |

**Open, documented, not fixed:** re-exported names not linked; literal `getenv` fallbacks not reported as secret defaults; coarse partial parsing; lexical retrieval misses paraphrases ([LIMITATIONS](../LIMITATIONS.md), backlog B-19, B-08).
**Pattern.** Of 21 defects, 1 was found by CI (DEF-19), 2 by user feedback (DEF-20, DEF-21) and 18 by running Raven against real services, a real repository or the labelled benchmark. None was found by reading code.

## 7. Not tested
Live AI answer quality; real email delivery; public HTTPS; load and concurrency beyond unit tests; accessibility audit; non-Chromium browsers; penetration testing; usability with real users; Linux hosts. Each is in the [backlog](05-PRODUCT-BACKLOG.md) or the [risk register](06-RISK-REGISTER.md).

## 8. Exit criteria
| Criterion | Target | Actual | Met |
|---|---|---|:-:|
| Backend tests | all pass | 490 pass, 1 opt-in skipped | ✅ |
| Lint | clean | clean | ✅ |
| Benchmark gates | all pass | 22 of 22 | ✅ |
| Known high-severity defects open | 0 | 0 | ✅ |
| Migrations reversible and backed up | yes | yes (dumps before 0005, 0007, 0008) | ✅ |
| From-scratch image build | succeeds | succeeds | ✅ |
| CI pipeline | green run | first run failed, fixed, not yet green | ⚠️ |
| Live AI answer verified | one successful answer | none | ❌ |
| Real users tested the UI | at least five | none | ❌ |

## 9. Sign-off
**Conditional pass.** Raven passes for local use, review and demonstration from the repository. It is **not** signed off for public hosting or for claims about AI answer quality, because a live-model check, a green CI run and a hosted trial have not happened. Conditions to close: B-01, B-02, B-04, B-09. See [release readiness](10-RELEASE-READINESS.md).
