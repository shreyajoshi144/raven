# Portfolio and resume guide

How to describe Raven honestly and memorably: the one-line pitch, resume bullets with numbers you can defend, a two-minute demo, and the questions to expect. Every number below was measured on this repository (command or file noted); nothing is rounded up.

## The "I built X for Y" sentence
> **Built Raven, an evidence-backed codebase-onboarding platform for developers joining unfamiliar FastAPI projects**: paste a public GitHub repo and get, pinned to one commit, an interactive architecture map, a readiness report, change-impact analysis and cited Q&A, where every claim links to a file, a line range and how it was established.

Short form (profile / README header): *Raven turns a GitHub repo into a map new engineers can verify, not just trust.*

> The project-management side of this work (charter, requirements, roadmap, milestones, backlog, risk register, QA report, closure report) is in [project/](project/README.md).

## Numbers recruiters respond to
Hiring managers look for five things: **scale, accuracy, speed, quality discipline and cost awareness**. Raven has a measured answer to each.

| Signal | Number | Where it comes from |
|---|---|---|
| Quality discipline | **490 automated tests** passing (≈4.8k lines of tests against ≈10.3k lines of backend), real PostgreSQL, 0 mocks of the database | `cd backend && python -m pytest -q` |
| Accuracy (graph) | **100 % precision and recall on 30 labelled routes; 99 % recall / 100 % precision on 100 import edges** across 3 benchmark repos | `python -m evals run --suite smoke` (run on 2026-11-25) |
| Accuracy (analysis) | readiness rules **precision 1.00, recall 0.94** (17 labelled findings); change-impact **100 % recall on 38 affected routes and 27 modules**, 0 false positives | same run |
| Trust | **100 % citation validity**: every cited path and line range exists (24 citations checked); answers carry a rule-based confidence label and separate *inferred* claims | same run |
| Speed | a real 711-node, 1,603-edge, 23-route repository (`fastapi/full-stack-fastapi-template`) analysed **end to end in 11.3 s** with no LLM calls | recorded in [evaluation/EVALUATION_AND_RESULTS.md](evaluation/EVALUATION_AND_RESULTS.md) |
| Evaluation maturity | a versioned benchmark with a stored baseline and **metric gates**: the run above shows score deltas against the baseline (e.g. readiness precision 0.88 → 1.00, impact route recall 0.87 → 1.00) | `backend/evals/`, [evaluation/AI_EVALUATION.md](evaluation/AI_EVALUATION.md) |
| Production thinking | per-user **daily quotas** (analyses, questions, tokens, spend), per-route **rate limits**, an **abuse switch** with audit trail, answer and embedding **caches**, a **monitoring dashboard** and Prometheus endpoint | [ADMIN_AND_OPERATIONS.md](ADMIN_AND_OPERATIONS.md) |
| Breadth | **67 API routes**, 8 Alembic migrations, 3 n8n workflows, React 18 SPA with an SVG graph engine (pan, zoom, fit, minimap), Docker Compose stack with proxy, backup and monitor profiles | `docker compose up -d --build` |

### Resume bullets (pick 3 to 5)
- Built **Raven**, a full-stack codebase-analysis platform (FastAPI, PostgreSQL, React, n8n, Docker) that maps a public FastAPI repo into a commit-pinned architecture graph, readiness report, change-impact analysis and cited Q&A; analysed a 711-node, 23-route repo in **11.3 s**.
- Designed a **benchmark-driven evaluation harness** (3 labelled repos, versioned fingerprint, stored baseline, metric gates): achieved **100 % route precision/recall, 99 % import-edge recall and 100 % citation validity**, and used it to catch regressions (readiness precision 0.88 → 1.00).
- Engineered **grounded AI answers**: deterministic retrieval, schema-validated model output, citations checked against retrieved evidence, a rule-based confidence label, and automatic retrieval-only fallback when the model is unavailable, so the product never fabricates output.
- Hardened for launch: Argon2id + TOTP 2FA, CSRF + origin checks, strict CSP and security headers, secret redaction, SSRF-safe GitHub access, DB-backed rate limits, **per-user daily quotas with a token/spend cap**, and an admin console with an abuse switch and audit log.
- Cut repeat-question cost to zero model calls with a **commit-keyed answer cache** shared across users, and shipped an **operations dashboard** (latency percentiles, error rate, queue health, AI fallback rate) plus a Prometheus endpoint.
- Wrote **490 tests** against a real PostgreSQL (state machine transition matrix, idempotent webhooks, concurrency, migrations) and ran the full stack in Docker with PostgreSQL as both state store and work queue (`FOR UPDATE SKIP LOCKED` leases).

### Number formulas, if you adapt the sentence
*Built **X** (what) for **Y** (who), which **verb + metric** (speed / accuracy / cost / scale) measured by **how** (benchmark, test count, load test).* Strong example: "…analysed a 23-route repo in 11.3 s and scored 1.00 route precision/recall on a 30-route labelled benchmark."
Avoid unmeasurable claims ("high performance", "scalable"). Do not claim users, traffic or revenue; Raven has none.

## Two-minute demo
1. **Landing → sign up** (30 s): show the sign-in simplicity and that the app is real, not a mock.
2. **Paste a repo** (20 s): watch the pipeline states; mention "pinned to a commit, never executes code".
3. **Map** (40 s): zoom, select a route, show the connection labels and the evidence panel with file and line; click *Open source*.
4. **Ask** (20 s): ask where authentication is enforced; point at citations, confidence label, and "inferred" section. Mention the fallback when no model key is set.
5. **Admin → Monitoring** (10 s): quotas, abuse switch, latency and queue charts.

## Questions to expect, and the honest answers
| Question | Answer |
|---|---|
| Why PostgreSQL as the queue? | One datastore means transactional state changes and enqueueing; `SKIP LOCKED` leases give at-least-once work with idempotency keys. The trade-off is throughput ceiling versus a broker, acceptable at this scale. |
| How do you know answers are not hallucinated? | Output is schema-validated; every citation must overlap a retrieved snippet; the confidence label is a rule over evidence, not a model probability; unverifiable claims are listed as *inferred*. |
| Why n8n? | It sequences, polls, retries and times out; the backend owns every state transition and n8n holds no credentials. The contract is idempotent, so replays are safe. |
| What would you do next? | Run the eval on an LLM-backed system under test (the opt-in `eval-live` workflow exists), get the CI evaluation gate to a green run, a real HTTPS deployment, threshold alerts, and pgvector once node counts grow. |

## What is not verified (say this out loud)
- **AI answer quality** has not been measured with a live model; the evaluated system is retrieval-only. Retrieval-only scores are modest (hit@5 0.55, MRR 0.37, up from the stored baseline 0.45 and 0.31).
- No real SMTP delivery, no real public HTTPS domain, no load test, and the GitHub Actions run is not yet green (the pipeline, including an evaluation gate on `evals/thresholds/smoke.json`, is defined; its first run failed at lint and was fixed in `1021a57`).
- The 11.3 s figure is a single recorded run on a laptop, not a benchmark distribution; the suite also has 1 opt-in test that is skipped.
- Spend is computed from configured list prices, not provider invoices; PR-review tokens are not counted toward quotas.
