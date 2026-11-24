# Raven: case study

**One line:** a way for a developer joining an unfamiliar FastAPI codebase to see how it fits together, with every claim traceable to a file, a line range and how it was established.

## The problem and who has it
A new developer spends days answering basic questions: where requests enter, which routes exist, what a change will touch. Generic AI chat answers instantly but cannot show where an answer comes from, so it cannot be checked, and a wrong answer about unfamiliar code is expensive.
**Primary user:** an engineer onboarding onto a Python/FastAPI service. **Secondary:** a tech lead reviewing a repository or a pull request.
*Status of this claim: a hypothesis from the problem itself. I have not run user interviews, so I do not report adoption or time saved.*

## What I decided to cut, and why
Trust was the product, so I cut anything that would let an unverifiable claim in.

| Cut | Why | What I did instead |
|---|---|---|
| Running or tracing the code | Executing untrusted repositories is a security risk and makes results non-deterministic | Static analysis only; edges are labelled *verified*, *inferred* or *unresolved* |
| Languages other than Python/FastAPI | Accuracy needs depth, and I could only hand-label a benchmark for one stack | Other languages get modules and imports only, stated in the UI |
| Private repositories and GitHub sign-in | Holding access to people's source code is a liability I could not justify for v1 | Public repos only; the token needs no scopes |
| A free-form chatbot | An uncited answer cannot be checked | Every answer cites code; citations are validated against retrieved evidence; with no model, users still get source locations |
| Model-reported confidence | A model's own confidence is not explainable | A rule over the evidence: high, medium or low |
| Multi-model routing, SMS or WebAuthn login, scale infrastructure | Real, but not needed to prove the core idea | A fallback model for availability only; TOTP 2FA; per-job caps instead of load claims |

## How I measured quality
Quality is judged by a versioned benchmark of **3 hand-labelled repositories** with a stored baseline and pass/fail gates, run with no model and no network so results are repeatable.

| What | Score (run 2026-11-23) | Labelled items |
|---|---|---|
| Routes found | precision 1.00, recall 1.00 | 30 |
| Import edges | precision 1.00, recall 0.99 | 100 |
| Readiness findings (rule level) | precision 1.00, recall 0.94 | 17 |
| Change impact, affected routes | recall 1.00 | 38 |
| Citations that point to real code | 1.00 | 24 |
| Retrieval, correct evidence in top 5 | 0.55 (baseline 0.45) | 20 |

The benchmark caught real defects: newer Python syntax silently dropping whole files, and non-deterministic retrieval. Both were fixed and now have regression tests. Alongside it sit 483 automated tests on a real PostgreSQL.

**Not measured:** AI answer quality with a live model. The evaluated system is the retrieval-only path. Retrieval is the weakest number (hit@5 0.55) and the next thing I would improve.

## What I would do next
Measure the answers with a live model and a judge, add an eval gate to CI, and interview five developers to test the core claim.
