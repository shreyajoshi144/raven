# Raven — delivery history in sprints

> Related: [Product](../product/PRODUCT.md) · [Architecture](../architecture/ARCHITECTURE_AND_WORKFLOWS.md) · [Evaluation](../evaluation/EVALUATION_AND_RESULTS.md) · [Testing log](../testing/TESTING_LOG.md)

Reconstructed from the changelog, migration dates, file timestamps and the working record of each pass. Sprint 0–1 dates are approximate (from file timestamps); Sprints 2–7 dates are exact. Test counts are the backend `pytest` totals recorded at the end of each sprint.

```mermaid
gantt
  title Raven delivery (2026)
  dateFormat YYYY-MM-DD
  axisFormat %b %d
  section Foundation
  S0 MVP (approx dates)                :done, s0, 2026-10-14, 5d
  S1 Analyzer 1.1.0                    :done, s1, 2026-10-19, 1d
  section Verification and UI
  S2 UI integration and real n8n run   :done, s2, 2026-10-26, 1d
  S3 Recruiter documentation           :done, s3, 2026-10-26, 1d
  section Quality engineering
  S4 AI evaluation framework           :done, s4, 2026-10-26, 1d
  S5 Defect fixes                      :done, s5, 2026-10-27, 6d
  section Productisation
  S6 Sign-up, React UI, deploy profiles :done, s6, 2026-11-01, 1d
  S7 Package and roadmap               :active, s7, 2026-11-01, 1d
```

## At a glance
| Sprint | Goal | Backend tests at end | Headline result |
|---|---|---:|---|
| S0 | Working MVP: analyze a public FastAPI repo, graph, guide, cited Q&A | 250 | Orchestrated by n8n, state and queue in PostgreSQL; verified against fakes and an n8n interpreter |
| S1 | Analyzer 1.1.0: readiness report, change impact, Q&A confidence, frontend linkage | 320 | API-only features, migration `0002` |
| S2 | Make S1 visible and prove the stack | 347 | Health/Impact/Ask screens; **first run in real n8n under Docker** |
| S3 | Recruiter-ready docs | 347 | 4 documents, diagrams, real screenshots |
| S4 | Measure Raven instead of asserting it | 373 | Benchmark v1 + harness; **found 5 real defects** |
| S5 | Fix what the benchmark found | 387 | 22/22 gates; every metric improved or equal except one regression found and fixed |
| S6 | Public sign-up readiness | 403 | Email verification, reset, TOTP 2FA, React UI, HTTPS/backup/monitor profiles |
| S7 | Package and plan production grade | 403 | This package; roadmap below |

## S0 — MVP
**Goal:** a developer pastes a public GitHub repo and gets an evidence-backed map.
**Delivered:** FastAPI API with sessions/CSRF/ownership checks; Python worker with a PostgreSQL queue (`SKIP LOCKED`, leases); three generated n8n workflows; static analysis with Python `ast`; graph with verified/inferred/unresolved edges; 14-section guide; cited Q&A with retrieval-only fallback; vanilla-JS UI with an interactive Map; Docker Compose; 250 backend tests; Docker-free Playwright flow.
**Not verified at the time:** real n8n, Docker build, live GitHub, live LLM.

## S1 — Analyzer 1.1.0
**Delivered:** frontend files scanned as text and linked to routes (never marked verified); engineering-readiness report (severity and confidence kept separate; evidence mandatory); change impact (GitHub compare mapped onto the graph); Q&A `confidence` label and separate `inferred` list; migration `0002`.
**Carried over:** no UI for the new features; workflows and Docker still unverified.

## S2 — UI integration and real-stack proof
**Delivered:** Health (filters, evidence → exact source line), Impact (base picker, tables, graph, history), Ask (confidence + inferred shown apart from cited answer); DOM-free helpers with unit tests; 27 new tests (API contracts, workflow validation, config).
**Verified:** full Docker Compose stack, all health checks, three workflows active in **real n8n 2.43.4**, one real repository analysed end to end.
**Found and fixed by running it:** `.env.example` inline comments made Docker Compose send a bogus GitHub token (every analysis failed `REPO_FORBIDDEN`); a helper silently dropped `data-*` attributes (broken guide highlight); phone-width overflow.

## S3 — Recruiter documentation
**Delivered:** product, architecture and evaluation documents, README, 11 real screenshots, a verified-vs-untested convention (✅ / 📄 / ⬜), a clean ZIP.

## S4 — AI evaluation framework
**Delivered:** `backend/evals` harness (`validate`, `run`, `report`, `verify-sources`); benchmark v1 (3 repos incl. one real, 27 questions of which 7 unanswerable, 30 routes, 100 import edges, 5 impact scenarios); deterministic metrics; optional DeepEval judge kept out of the runtime dependencies; threshold gates, baseline comparison, CI smoke job and an opt-in live workflow.
**Found:** five Raven defects (unparseable newer syntax dropping a whole file, non-deterministic retrieval, SQLModel ORM misclassification, `os.getenv` misrule, line-count off-by-one).

## S5 — Defect fixes
Each fix has a regression test that failed first.
| Fix | Before → after (smoke suite, retrieval-only) |
|---|---|
| Tolerant parsing with exact line numbers and honest reporting | import-edge recall 0.90 → 0.99 |
| Deterministic retrieval (stable tie-breakers) | outputs differing between repeats: 5 → 0 |
| SQLModel `table=True` through a base class | ORM recall 0.50 → 1.00 |
| `os.getenv` rule, trailing-newline line counts | readiness rule precision 0.88 → 1.00 |
| `SEC-UNAUTH-MUTATION` auth recognition (exposed by fix 1) | location precision 0.67 → 1.00 |
**Regression caught by the harness itself:** empty files produced "lines 0–0" evidence (citation validity 0.966); fixed with a test. Thresholds were only ever raised.

## S6 — Public sign-up, React UI, deploy profiles
**Delivered:** email verification, password reset, TOTP 2FA with recovery codes (migration `0003`, 15 tests); React + Vite + plain CSS frontend reusing the graph engine; Caddy HTTPS, backup and monitor Compose profiles.
**Verified:** full-stack browser run (register → analyze → every tab → 2FA setup and login → recovery code), backup **restore** with matching row counts, Caddy config validation.
**Found and fixed by running it:** Compose required `RAVEN_DOMAIN` even with the proxy profile off; backup housekeeping used wrong table/column names; mobile overflow on logged-in pages.

## S7 — Package and production-grade plan
```mermaid
flowchart LR
  A["Verify what exists<br/>live-model eval · CI on GitHub<br/>public HTTPS deploy · SMTP"] --> B["AI engineering rigor<br/>injection tests · provider fallback<br/>in-app cost/latency · feedback loop"]
  B --> C["Operations<br/>OpenTelemetry · metrics · alerts<br/>supply-chain scans · Helm/Terraform"]
  C --> D["Customer readiness<br/>SSO · orgs/roles · GitHub App<br/>PR comments · runbooks · threat model"]
```
**Next sprint candidates, in order:** (1) live-model evaluation with the judge and AI-quality floors; (2) CI executed on GitHub; (3) public deployment on a Linux host with a real certificate and SMTP; (4) prompt-injection test set; (5) OpenTelemetry + Prometheus.

## Defects found by verification, by sprint
```mermaid
flowchart LR
  S2["S2 run in real stack<br/>3 defects"] --> S4["S4 benchmark<br/>5 defects"] --> S5["S5 fixing<br/>1 regression (caught + fixed)"] --> S6["S6 full-stack run<br/>3 defects"]
```
Every defect above was found by *running* something against real data, not by reading code, which is the working method of the whole project.
