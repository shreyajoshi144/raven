# Milestones

| | |
|---|---|
| Version / date | 1.0 · 2026-11-25 |
| Related | [Roadmap](03-ROADMAP.md) · [Sprint history](../sprints/SPRINTS.md) · [QA report](08-QA-REPORT.md) |

Each milestone has an exit criterion that was checked, and a pointer to the evidence. Status: **Done**, **Partial** or **Planned**.

| ID | Milestone | Date | Exit criterion | Evidence | Status |
|---|---|---|---|---|---|
| M1 | MVP end to end | 2026-10-14 to 10-18 (approx.) | A public repository becomes a graph, guide and cited answer, orchestrated by n8n with state in PostgreSQL | Sprint S0; 250 tests at the time | Done |
| M2 | Analyzer 1.1.0 | 2026-10-19 | Readiness, change impact and Q&A confidence available through the API | Migration `0002` (dated 2026-10-19); S1 | Done |
| M3 | Real-stack verification | 2026-10-26 | Full Docker stack and three workflows active in real n8n; one real repository analysed | S2; [evaluation §3](../evaluation/EVALUATION_AND_RESULTS.md) | Done |
| M4 | Evaluation baseline | 2026-10-26 | Versioned benchmark with ground truth; baseline run recorded | Run `ab282dbf401f`; [AI evaluation](../evaluation/AI_EVALUATION.md) | Done |
| M5 | Quality gates met after fixes | 2026-10-27 to 11-01 | All gates pass after fixing the defects the benchmark found | Run `50744a933fd3`, 22 of 22 | Done |
| M6 | Public sign-up readiness | 2026-11-01 | Email verification, password reset, TOTP, React frontend, deployment profiles; AI hardening | Migrations `0003`, `0004`; 428 tests | Done |
| M7 | Intelligence upgrade | 2026-11-02 to 11-03 | Commit-aware answers, incremental indexing, architecture drift, pull-request review | Migrations `0005`, `0006`; [UPGRADE_PLAN](../sprints/UPGRADE_PLAN.md) | Done |
| M8 | Local deployment validated | 2026-11-03 | Backup taken; migrations applied to the real database; API, worker, n8n, analysis, Ask, Architecture and review exercised | S11; 462 tests; one defect found and fixed | Done |
| M9 | UI redesign | 2026-11-05 | Landing, sign-in and workspace redesigned; browser-verified | S12 | Done |
| M10 | Operations hardening | 2026-11-07 | Admin console, quotas, caches, monitoring and headers working and tested | Migrations `0007`, `0008`; 483 tests | Done |
| M11 | Recruiter-ready documentation | 2026-11-23 | API, configuration, operations and portfolio documents; benchmark re-run | S14 | Done |
| M12 | First-time-user fixes | 2026-11-24 | Architecture-first Map, scroll-to-pan, plain-language review, false alarms fixed | S15; 489 tests | Done |
| M13 | Public repository with passing CI | 2026-11-25 | Repository connected; CI green | Repository connected; first run failed at lint, fixed in `1021a57`; green run not yet recorded | **Partial** |
| M14 | Live-model verification | not scheduled | One successful live answer; benchmark with the judge | Blocked: LLM account has no credit | Planned |
| M15 | Hosted demo | not scheduled | Reachable over HTTPS with spend limits and real email | Needs a server, domain and SMTP | Planned |

Planned versus actual: there was no schedule baseline, so slippage cannot be reported. The one forward plan that existed ([UPGRADE_PLAN](../sprints/UPGRADE_PLAN.md), three sprints each awaiting approval) was delivered as M7 in two days.
