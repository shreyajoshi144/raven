# Project charter

| | |
|---|---|
| Project | Raven: evidence-backed codebase onboarding |
| Version / date | 1.0 · 2026-11-25 (written at closure from the working record; see "How this charter was made") |
| Owner | Shreya Joshi (product owner, project manager, developer, tester) |
| Status | Closed with conditions; see [closure report](11-PROJECT-CLOSURE-REPORT.md) |

## 1. Problem and opportunity
A developer joining an unfamiliar codebase spends days working out where requests enter, which routes exist and what a change will touch. General AI chat answers quickly but cannot show where an answer comes from, so it cannot be checked. Raven gives a new developer a map and a set of answers where every claim points to a file, a line range and how it was established.
*Status of this claim: a hypothesis from the problem itself. No user interviews were held.*

## 2. Objectives and success criteria
| ID | Objective | Success criterion | Result |
|---|---|---|---|
| O1 | End-to-end analysis of a public FastAPI repository | FR-01 to FR-10 delivered and tested | Met |
| O2 | Quality that is measured, not asserted | A versioned benchmark with pass/fail gates; all gates pass | Met: 22 of 22 (retrieval-only; [report](../evaluation/results/2026-11-25-smoke-current/report.md)) |
| O3 | Trustworthy AI behaviour | Answers cite validated evidence; a safe fallback when the model is unavailable | Partly met: verified with fakes and a real quota failure; no successful live answer |
| O4 | Operable by its owner | Admin console, quotas, monitoring, security headers, backups, health checks | Met locally; not hosted |
| O5 | Understandable to a first-time user | Plain language, architecture-first navigation | Partly met: improved after review feedback; no usability test with users |
| O6 | Portfolio-ready record of the work | Consistent documentation, public repository, project-management pack | Met once the repository push and CI run are complete |

The success criteria for O2 are the gates in `backend/evals/thresholds/smoke.json`, set in S4 and only ever raised. Criteria for O1, O3 to O6 were written retrospectively from the requirements; there was no formal approval step.

## 3. Scope
**In scope.** Public GitHub repositories at the default branch head; Python/FastAPI modelling (other languages: modules and imports only); static analysis; map, guide, readiness, impact, architecture drift, pull-request review and cited Q&A; accounts with verification, reset and TOTP; admin console, quotas, caches and monitoring; Docker Compose deployment.
**Out of scope (cut on purpose; reasons in the [case study](../CASE_STUDY.md) and [decision log](07-DECISION-LOG.md)).** Running or tracing the analysed code; private repositories and GitHub sign-in; languages beyond Python; a free-form chatbot without citations; model-reported confidence; multi-model routing; SMS or WebAuthn login; load testing and scale infrastructure; posting comments to GitHub.

## 4. Deliverables
The application (API, worker, three n8n workflows, React frontend), 8 database migrations, a benchmark and evaluation harness, 490 automated tests, Docker Compose deployment with proxy, backup and monitor profiles, and the documentation set in [docs/](../README.md) including this pack.

## 5. Timeline
No fixed deadline or up-front schedule baseline was set. The work ran sprint by sprint from 2026-10-14 to 2026-11-25 (S0–S16). See [roadmap](03-ROADMAP.md) and [milestones](04-MILESTONES.md).

## 6. Resources, budget and constraints
| Item | Position |
|---|---|
| People | One person. An AI coding assistant (Claude Code) was used as a pair programmer; scope, priorities, acceptance and review were the owner's. Commit trailers record the assistance. |
| Budget | No paid infrastructure. Everything ran on one laptop with Docker. The LLM account has no credit, so model spend is zero. Effort in hours was not tracked. |
| Constraints | GitHub public data only; one machine (macOS, arm64); no hosted environment; GitHub API rate limits (60 per hour without a token) |
| Assumptions | Developers will paste public repositories; static analysis is useful even where it cannot prove runtime behaviour; labelled uncertainty is better than confident guesses |
| Dependencies | GitHub API and codeload; an LLM provider (optional); n8n 2.43.4; PostgreSQL 16; Docker |

## 7. Stakeholders and communication
| Stakeholder | Interest | How they are kept informed |
|---|---|---|
| Shreya Joshi (owner) | Delivers and decides | Working record, sprint documents |
| Intended users: developers onboarding onto FastAPI services; tech leads reviewing pull requests | Understand a codebase quickly and verifiably | The product itself; the README and screenshots |
| Reviewers of the repository (for example hiring managers) | Evidence the work is real and honest | This pack, the QA report and the closure report |

There was no client or sponsor. Communication is by documents in the repository.

## 8. Governance
- **Definition of done.** Code merged with tests that failed before the fix where a defect was involved; lint clean; migrations reversible with a backup taken first; documentation updated; claims labelled verified, reported or not verified.
- **Change control.** Scope changes are recorded in the [decision log](07-DECISION-LOG.md) and the [changelog](../../CHANGELOG.md); cuts are recorded in the PRD.
- **Quality gates.** The benchmark gates in `backend/evals/thresholds/`, CI lint and tests, and `scripts/check_docs.py` for documentation consistency.
- **Risk management.** [Risk register](06-RISK-REGISTER.md), reviewed at each sprint boundary.

## 9. How this charter was made
Raven started as a working build, not a chartered project. The charter, PRD and other management documents were written on 2026-11-25 from the working record (sprint notes, changelog, migrations, test and evaluation output). Dates before S8 are approximate where marked in [SPRINTS.md](../sprints/SPRINTS.md).
