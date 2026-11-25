# Product backlog

| | |
|---|---|
| Version / date | 1.0 · 2026-11-25 |
| Related | [Roadmap](03-ROADMAP.md) · [PRD](02-PRD.md) · [Risk register](06-RISK-REGISTER.md) |

**Prioritisation:** MoSCoW. **Size** is an effort estimate for one person, not a commitment: XS under 2 hours, S under a day, M one to three days, L more than three days. "Blocked" means the owner cannot proceed without something external.

## 1. Open items (ordered)
| ID | Item | Priority | Size | Status | Requirement / risk | Notes |
|---|---|---|---|---|---|---|
| B-01 | Produce one successful live AI answer; run the benchmark with the judge and set AI-quality floors | Must | S | Blocked: LLM account has no credit | FR-08, NFR-03 · R-02 | The opt-in `eval-live` workflow already exists |
| B-02 | Record a green GitHub Actions run | Must | XS | Open: first run failed at lint, fixed in `1021a57` | NFR-10 · R-16 | Push, then read the run |
| B-03 | Recreate the running local stack from the from-scratch image | Should | XS | Open | NFR-08 · R-12 | The running images were layered during a network outage |
| B-04 | Hosted demo: small server, HTTPS, low spend limits | Should | M | Open | NFR-07 · R-20 | Needs a domain and a server |
| B-05 | Send and receive real verification and reset emails | Should | S | Open | FR-11 · R-08 | Needs an SMTP provider |
| B-06 | Alert thresholds (error rate, queue age, AI fallback rate) | Should | M | Open | FR-15 | The metrics exist; nothing alerts |
| B-09 | Interview five developers on the Map and the pull-request page | Should | S | Open | PRD P1, P2 · R-15 | Tests the core claim |
| B-10 | Refresh the browser (Playwright) suites for the redesigned UI and add the Map | Should | M | Open | NFR-10 | Current UI checks are manual |
| B-07 | Load test and capacity numbers | Could | M | Open | NFR-04 · R-07 | Per-analysis caps exist; concurrency is untested |
| B-08 | Measure semantic retrieval; move vectors to pgvector at scale | Could | L | Open | FR-08 · R-02 | Retrieval hit@5 is 0.55 |
| B-11 | Fix the Guide scrolling sideways at 375 px | Could | S | Open | NFR-06 | Wide diagrams and tables |
| B-16 | Automatic data-retention expiry | Could | S | Open | NFR-09 | Users delete analyses manually |
| B-17 | PostgreSQL row-level security as a second tenant barrier | Could | M | Open | NFR-09 | Isolation is application-level today |
| B-18 | Count pull-request-review tokens toward quotas | Could | S | Open | FR-13 | Known gap |
| B-19 | Parser and rule gaps: re-exported names, literal `getenv` fallbacks, finer partial parsing | Could | M | Open | FR-03, FR-06 | Listed in [LIMITATIONS](../LIMITATIONS.md) |
| B-20 | Store prompts as released, versioned artifacts | Could | S | Open | FR-08 | Today a content hash is recorded |
| B-12 | Private repositories through a GitHub App | Won't (now) | L | Deferred | PRD non-goal | Needs scoped credentials |
| B-13 | Post review comments to GitHub | Won't (now) | M | Deferred | PRD non-goal | Needs write access |
| B-14 | Additional languages | Won't (now) | L | Deferred | PRD non-goal | Needs labelled benchmarks per language |
| B-15 | Single sign-on and organisations | Won't (now) | L | Deferred | NFR-01 | After the single-user case is proven |

## 2. Delivered epics
| Epic | Delivered | Requirements | Sprint |
|---|---|---|---|
| E1 | Submit, pin and run the pipeline with n8n and a PostgreSQL queue | FR-01, FR-02 | S0 |
| E2 | Evidence graph, onboarding guide, readiness, change impact | FR-03, FR-05, FR-06, FR-07 | S0–S2 |
| E3 | Evaluation framework and benchmark; defects fixed | NFR-03 | S4–S5 |
| E4 | Accounts: verification, reset, TOTP; React frontend; deployment profiles | FR-11, NFR-08 | S6 |
| E5 | AI hardening: fallback model, optional semantic retrieval, versioning, injection suite | FR-08 | S6 |
| E6 | Commit awareness, incremental indexing, architecture drift, pull-request review, usage accounting | FR-09, FR-10, FR-16, FR-17 | S8–S10 |
| E7 | Local deployment validation and the dispatch fix | NFR-02, NFR-07 | S11 |
| E8 | Redesigned landing, sign-in and workspace | NFR-06 | S12 |
| E9 | Admin console, quotas, caches, monitoring, security headers | FR-12 to FR-15, NFR-01 | S13 |
| E10 | Architecture-first Map; plain-language pull-request review | FR-04, FR-10, NFR-06 | S15 |
| E11 | Documentation, repository, CI fix, project-management pack | NFR-10 | S14, S16 |

## 3. Backlog hygiene
Items leave the backlog when their evidence exists (a test, a run or an observed result). Deferred items stay visible with their reason. IDs are stable and referenced by the roadmap, the risk register and the closure report.
