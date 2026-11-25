# Project closure report

| | |
|---|---|
| Project | Raven: evidence-backed codebase onboarding |
| Period | 2026-10-14 to 2026-11-25 (about 6 weeks, 17 sprints) |
| Prepared by | Shreya Joshi, 2026-11-25 |
| Status | **Closed with conditions** (see §9) |
| Related | [Charter](01-PROJECT-CHARTER.md) · [PRD](02-PRD.md) · [QA report](08-QA-REPORT.md) · [Risk register](06-RISK-REGISTER.md) |

## 1. Summary
Raven takes a public GitHub FastAPI repository and returns an architecture map, an onboarding guide, readiness findings, change impact, a plain-language pull-request review and cited answers, with every claim pinned to a commit, a file and a line range. It was built and verified locally, measured against a hand-labelled benchmark, hardened for operation (admin console, quotas, caches, monitoring, security headers) and documented. It has not been hosted publicly, and AI answer quality has not been measured with a live model.

## 2. Objectives against results
| Objective | Result | Evidence |
|---|---|---|
| O1 End-to-end analysis (FR-01 to FR-10) | **Met** | [Traceability](09-TRACEABILITY-MATRIX.md): all implemented and tested |
| O2 Measured quality with gates | **Met** | 22 of 22 gates; 5 benchmark-found defects fixed ([QA report §4](08-QA-REPORT.md)) |
| O3 Trustworthy AI behaviour | **Partly met** | Validation and fallback verified with fakes and one real quota failure; no successful live answer |
| O4 Operable by its owner | **Met locally** | Admin console, quotas, monitoring, backups; not hosted |
| O5 Understandable to first-time users | **Partly met** | Map and review page rewritten after feedback; no user testing |
| O6 Portfolio-ready record | **Met** | This pack, consistent documentation, repository |

## 3. Scope
**Delivered:** all 17 functional and 10 non-functional requirements in the [PRD](02-PRD.md) have an implementation and tests; 7 of the 27 are only partly verified.
**Cut on purpose:** running code, private repositories, other languages, an uncited chatbot, model-reported confidence, multi-model routing, SMS and WebAuthn login, scale infrastructure, posting to GitHub ([PRD §6](02-PRD.md#6-what-was-cut-and-why)).
**Added during delivery (not in the first MVP):** commit-aware and incremental analysis, architecture drift, pull-request review, admin console, quotas, caches, monitoring, the architecture-first Map. Each was added after the previous milestone was verified, and each is traced to a requirement.

## 4. Schedule
There was no up-front schedule baseline, so variance cannot be reported. Actual: MVP in the first week (S0, approximate dates), verification and evaluation in the second, productisation and the intelligence upgrade by 2026-11-03, launch preparation to 2026-11-07, documentation and usability fixes 2026-11-23 to 2026-11-25. See [milestones](04-MILESTONES.md). The one forward plan ([UPGRADE_PLAN](../sprints/UPGRADE_PLAN.md)) was delivered in two days.

## 5. Resources and cost
One person with an AI coding assistant. No paid infrastructure; everything ran on one laptop. Effort in hours was not tracked. LLM spend is zero (the account has no credit); the platform can price token use once list prices are configured.

## 6. Quality
| Measure | Result |
|---|---|
| Backend tests | 490 passed, 1 opt-in skipped |
| Frontend tests | 9 legacy + 6 React-shell passed |
| Benchmark gates | 22 of 22 |
| Defects found and fixed | 21 ([log](08-QA-REPORT.md#6-defect-log)); 0 high-severity open |
| Open documented limitations | listed in [LIMITATIONS](../LIMITATIONS.md) and the [backlog](05-PRODUCT-BACKLOG.md) |
| Documentation consistency | checked by script |

## 7. Deliverables
Application ([API](../API.md), worker, 3 workflows, React frontend, 8 migrations, 21 tables, 67 routes); evaluation harness and archived runs ([results](../evaluation/results)); deployment profiles ([DEPLOYMENT](../DEPLOYMENT.md)); documentation ([docs index](../README.md)); this management pack ([index](README.md)).

## 8. Risks and issues at closure
Six risks occurred and were handled or partly handled (R-01, R-12, R-14, R-15, R-16, R-19). Open: R-02 (live answer quality), R-15 (usability), R-16 (green CI), R-20 (no hosted instance). Full list: [risk register](06-RISK-REGISTER.md).

## 9. Closure criteria
| Criterion | Met |
|---|:-:|
| All Must requirements implemented and tested | ✅ |
| No high-severity defect open | ✅ |
| Documentation complete and consistent | ✅ |
| Repository published | ✅ (push by the owner) |
| CI green | ❌ not yet recorded (B-02) |
| One live AI answer verified | ❌ blocked on LLM credit (B-01) |

The project is **closed with conditions**: B-01 and B-02 are Must items that remain open, and are the first things to do.

## 10. Lessons learned
**What worked**
- *Measure first.* The benchmark found five real defects that reading code had missed, and thresholds only ever moved up.
- *Record the cuts.* A written non-goals list stopped scope creep and became the best evidence of prioritisation.
- *Backend owns state.* Keeping decisions out of the workflow engine made failures recoverable; the one orchestration bug (DEF-14) was found and fixed in a day.
- *Backup before every migration* and never reset volumes: no data was lost through a disk-full failure and a Docker restart.
- *Label uncertainty.* "Proven" versus "best guess" in the product and "verified" versus "not verified" in the docs prevented overclaiming.

**What did not**
- *No user research.* The product was judged by its builder until review feedback on a real repository exposed an unreadable canvas and a contradictory verdict. Next time: show a prototype to users after the first working slice.
- *Tests with fakes left the live path unproven.* The AI path has never produced a real answer. Next time: fund the account before building features that depend on it.
- *Environment problems cost time* (full disk, PyPI unreachable inside Docker). Next time: check free disk space and a from-scratch build early.
- *Documents drifted.* Sprint numbering and test counts disagreed across files until they were reconciled. Next time: one source of truth per fact and a script to check it from the start.
- *CI failed on its first run* because the lint tool was not installed locally. Next time: run the CI commands locally before pushing.

## 11. Handover and next steps
Start with [backlog](05-PRODUCT-BACKLOG.md) items B-02 (push and read the CI run), B-01 (fund the LLM account, ask one question, run the judge), B-03 (recreate the local stack from the built image), then B-04, B-05 and B-09. Operations are described in [ADMIN_AND_OPERATIONS](../ADMIN_AND_OPERATIONS.md); configuration in [CONFIGURATION](../CONFIGURATION.md).

## 12. Sign-off
Prepared and accepted by: Shreya Joshi (owner), 2026-11-25. There is no separate sponsor or client.
