# Raven: project-management pack

**What this is.** The planning, quality and closure documents for Raven, an evidence-backed codebase onboarding tool, delivered between 2026-10-14 and 2026-11-25 by one person (Shreya Joshi) as product owner, project manager, developer and tester, working with an AI coding assistant (Claude Code) under her direction. Every document here is consistent with the others and with the product: numbers are checked by `scripts/check_docs.py`, and anything not verified is said so.

## Read in this order
| # | Document | Answers |
|---|---|---|
| 1 | [Project charter](01-PROJECT-CHARTER.md) | Why the project exists, objectives, scope, constraints, roles, how it was governed |
| 2 | [Product requirements (PRD)](02-PRD.md) | Who it is for, what it must do (FR-01 to FR-17), quality bars (NFR-01 to NFR-10), what was cut |
| 3 | [Roadmap](03-ROADMAP.md) | What was delivered, what is next and later |
| 4 | [Milestones](04-MILESTONES.md) | Dated milestones with exit criteria and the evidence for each |
| 5 | [Product backlog](05-PRODUCT-BACKLOG.md) | Prioritised open work (MoSCoW) and delivered epics |
| 6 | [Risk register](06-RISK-REGISTER.md) | 20 risks: which happened, how they were handled, what remains |
| 7 | [Decision log](07-DECISION-LOG.md) | 14 key decisions with options and consequences |
| 8 | [Test and QA report](08-QA-REPORT.md) | What was tested, results, 21 defects found and fixed, exit criteria, sign-off |
| 9 | [Traceability matrix](09-TRACEABILITY-MATRIX.md) | Requirement → implementation → tests → status |
| 10 | [Release readiness](10-RELEASE-READINESS.md) | Go / no-go checklist for demo and for public hosting |
| 11 | [Project closure report](11-PROJECT-CLOSURE-REPORT.md) | Outcomes against objectives, lessons learned, handover |

## The project in numbers (all verified on 2026-11-25)
| Measure | Value | Source |
|---|---|---|
| Duration | 2026-10-14 → 2026-11-25 (about 6 weeks), 17 sprints (S0–S16) | [SPRINTS.md](../sprints/SPRINTS.md) |
| Requirements | 17 functional, 10 non-functional | [PRD](02-PRD.md) |
| Backend tests | 490 passed, 1 opt-in test skipped (real PostgreSQL) | [QA report](08-QA-REPORT.md) |
| Frontend tests | 9 legacy + 6 React-shell tests passed | [QA report](08-QA-REPORT.md) |
| Benchmark | 22 of 22 quality gates pass (3 hand-labelled repositories) | [evaluation results](../evaluation/results/2026-11-25-smoke-current/report.md) |
| API | 67 routes, 21 database tables, 8 reversible migrations, 3 n8n workflows | [API.md](../API.md) |
| Defects found by testing and fixed | 21 | [QA report](08-QA-REPORT.md#6-defect-log) |

## Why the commit history is short
Raven was built before it was put in Git, so the GitHub history starts with one commit that holds the finished work. The real delivery trail is in these documents: [sprints](../sprints/SPRINTS.md) with dates, [changelog](../../CHANGELOG.md), dated database migrations, archived evaluation runs in [docs/evaluation/results](../evaluation/results), and the defect log in the [QA report](08-QA-REPORT.md). Work from this point on is tracked in commits and CI runs.

## What is not done
Said once here and in every relevant document: no successful live AI answer yet (the LLM account has no credit), no hosted public deployment, real email delivery untested, and a green GitHub Actions run is not yet recorded. See [release readiness](10-RELEASE-READINESS.md).
