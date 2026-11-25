# Product requirements document (PRD)

| | |
|---|---|
| Product | Raven |
| Version / date | 1.0 · 2026-11-25 |
| Owner | Shreya Joshi |
| Related | [Charter](01-PROJECT-CHARTER.md) · [Traceability](09-TRACEABILITY-MATRIX.md) · [Product description](../product/PRODUCT.md) |

## 1. Problem statement
Developers joining an unfamiliar codebase cannot quickly see how it fits together, and AI chat tools give answers they cannot verify. See the [charter](01-PROJECT-CHARTER.md#1-problem-and-opportunity).

## 2. Users and needs
| ID | Persona | Need | Evidence |
|---|---|---|---|
| P1 | **Onboarding developer** (primary): joins a Python/FastAPI service and needs to know where requests enter, what exists and what a change touches | A map they can understand without opening every file; answers they can check | Hypothesis, no interviews |
| P2 | **Tech lead or reviewer** (secondary): reviews a pull request or assesses a repository | A plain statement of what a pull request changes and where to look first | Review feedback on a real repository (S15) showed the first version was unclear and contradicted another reviewer |
| P3 | **Operator** (the owner): runs the platform | Control over who uses it, what it costs and whether it is healthy | Own requirement |

## 3. Goals, non-goals and success metrics
**Goals.** G1 a first-time user understands a repository without reading each file; G2 every claim is traceable; G3 quality is measured against labelled ground truth; G4 the platform is operable.
**Non-goals.** Running the analysed code; private repositories; languages beyond Python; replacing a human reviewer; a general-purpose chatbot.

| Metric | Target | Measured (2026-11-25) |
|---|---|---|
| Benchmark gates passing | all (22) | 22 of 22 |
| Route detection (30 labelled routes) | precision and recall 1.00 | 1.00 / 1.00 |
| Citation validity (24 checked) | 1.00 | 1.00 |
| Time to analyse a 23-route repository | no target set | 11.3 s (one recorded run) |
| Usability with real users | no target set | not measured |

## 4. Functional requirements
Priority uses MoSCoW. Status values: **Verified** (tests and observed), **Partial** (some of it verified), **Not verified**. Evidence per requirement: [traceability matrix](09-TRACEABILITY-MATRIX.md).

| ID | Requirement | Acceptance criteria | Priority | Status |
|---|---|---|---|---|
| FR-01 | Submit a public repository | Given a GitHub URL, when it is valid and public, then an analysis is pinned to the head commit; look-alike hosts, encoded paths and non-public repositories are rejected with a specific message; an identical finished analysis is reused | Must | Verified |
| FR-02 | Run and recover the pipeline | An analysis moves QUEUED → FETCHING → PARSING → BUILDING_GRAPH → GENERATING_DOCS → READY with visible progress; transient failures retry with backoff; users can cancel, retry and delete; a crash mid-pipeline recovers | Must | Verified |
| FR-03 | Build an evidence graph | Every node and edge carries file and line evidence and a resolution label (verified, inferred or unresolved); code is never executed | Must | Verified |
| FR-04 | Interactive Map | The architecture is shown first; clicking an area shows its groups, then its files with what each depends on and what uses it; scroll pans the detailed graph and ⌘/Ctrl + scroll zooms | Must | Verified |
| FR-05 | Onboarding guide | A 16-section guide with commit-pinned citations; marked partial when anything was skipped or AI text is unavailable | Should | Partial (AI prose never produced live) |
| FR-06 | Engineering-readiness findings | Findings carry severity, confidence, evidence and a recommendation; absence findings say what was searched; a fixed "not assessed" list | Must | Verified |
| FR-07 | Change impact | Comparing a base against the analysed commit lists changed files, dependent modules, affected routes and potentially relevant tests; hostile references are rejected before any GitHub call | Should | Verified |
| FR-08 | Cited Q&A | Answers cite retrieved code; citations are validated against supplied evidence; confidence is a rule over evidence; claims beyond the code are shown as inferred; without a model, source locations are returned | Must | Partial (fallback verified; live answer not) |
| FR-09 | Architecture drift | Between two commits: new or removed dependencies, import cycles, boundary violations, coupling and complexity growth, breaking changes | Should | Verified |
| FR-10 | Plain-language pull-request review | A review priority with plain reasons, what the PR does, changes by area, things to check with why each matters and proven-or-guess labels, what else it could affect; nothing posted to GitHub | Should | Verified |
| FR-11 | Accounts and sessions | Register, verify email, reset password, TOTP two-factor with recovery codes; sessions with CSRF protection | Must | Partial (real email delivery not tested) |
| FR-12 | Admin console | Admin-only API and screen: users, analyses, failed jobs, LLM spend, audit log; disable and enable a user (revokes sessions); admins cannot disable themselves or each other | Should | Verified |
| FR-13 | Usage controls | Daily per-user quotas (analyses, questions, tokens, optional spend) with per-user overrides; per-route rate limits | Should | Verified |
| FR-14 | Caching | Validated AI answers are reused for the same commit and question; question embeddings are reused; fallbacks are never cached | Could | Partial (never held a live answer) |
| FR-15 | Monitoring | HTTP latency and error series, job and queue health, AI latency and fallback rate, and a Prometheus endpoint | Could | Verified |
| FR-16 | Commit-aware and incremental analysis | Answers and findings carry their commit; a new commit reuses unchanged parsing; a full reindex is available; tenants are isolated | Should | Verified |
| FR-17 | Usage and cost accounting | Tokens and latency per answer; cost when list prices are configured | Could | Verified (unit level) |

## 5. Non-functional requirements
| ID | Requirement | Measure | Status |
|---|---|---|---|
| NFR-01 | Security | CSRF and same-origin checks; strict CSP and security headers; SSRF-safe GitHub access; Argon2id; no execution of analysed code; secret redaction | Verified by tests; not penetration-tested |
| NFR-02 | Reliability | State machine owned by the backend; idempotent callbacks; lease-based queue; crash recovery; reversible migrations | Verified |
| NFR-03 | Accuracy | Benchmark gates on routes, imports, readiness, impact, retrieval and citation validity | Verified on 3 labelled repositories only |
| NFR-04 | Performance | Per-analysis caps (2,000 files, 20 MiB source, 600 s); no latency target | 11.3 s for the sample repository; no load test |
| NFR-05 | Honesty | Nothing fabricated; every result labelled; limitations listed in the product and docs | Verified |
| NFR-06 | Usability | Plain language; architecture before detail; first-time guidance | Partial: improved after feedback; no usability test |
| NFR-07 | Operability | Health endpoints, JSON logs, backups, admin console, metrics | Verified locally |
| NFR-08 | Portability | Docker Compose; image builds from scratch | Verified 2026-11-25 |
| NFR-09 | Privacy | Owner-only access (foreign ids return 404); deleting an analysis cascades; evidence not retained after answering | Verified by tests |
| NFR-10 | Maintainability | Lint clean; 490 tests; migrations; documentation checked by `scripts/check_docs.py`; CI green | Partial: CI run not yet green |

## 6. What was cut and why
| Cut | Reason |
|---|---|
| Running or tracing code | Security risk; makes results non-deterministic |
| Other languages | Accuracy needs depth; only FastAPI could be labelled |
| Private repositories | Holding access to others' source is a liability |
| Chatbot without citations | An uncited answer cannot be checked |
| Model-reported confidence | Not explainable; replaced by a rule over evidence |
| Multi-model routing, SMS or WebAuthn, scale infrastructure | Not needed to prove the core idea |
| Posting review comments to GitHub | Needs write access; Raven only produces text to copy |

## 7. Assumptions, dependencies and open questions
Assumptions and dependencies are in the [charter](01-PROJECT-CHARTER.md#6-resources-budget-and-constraints). Open questions: do first-time users find the Map and the review page understandable (needs interviews, backlog B-09); how good are live model answers (needs credit, B-01).
