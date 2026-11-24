# Raven evaluation report

Run `ef5411364870` · 2026-10-27T09:41:20Z · 3.43 s · suite **smoke**

| | |
|---|---|
| System under test | Raven retrieval-only fallback (no LLM) |
| Judge | not_requested |
| Benchmark | raven-eval 1.0.0 · fingerprint `774e9bbd2a2b9fb5` · repos: shop_api, clean_service, fastapi_template |
| Environment | Python 3.12.15 · analyzer 1.1.0 · commit `cd35b88f6186` (uncommitted changes) · DeepEval not installed |
| Repeats | 3 |

## Not evaluated in this run

- **AI answer quality was not measured**: no AI answers were produced (SUT mode `retrieval_only`). Key-fact recall, deterministic accuracy, abstention and judge metrics are therefore `—`, not zero. Citation metrics describe Raven's retrieval-only fallback answers.
- **LLM-as-judge: not_requested** — EVAL_JUDGE_PROVIDER is not set (deterministic metrics only)

## Scores

`—` = not measurable in this run (no samples or not applicable). n = labelled items behind the score.

| Metric | Value | n | Baseline | Δ | Gate |
|---|---:|---:|---:|---:|---|
| Graph · routes precision | 1.000 | 30 | 1.000 | +0.000 | ≥ 1.0 ✅ |
| Graph · routes recall | 1.000 | 30 | 1.000 | +0.000 | ≥ 1.0 ✅ |
| Graph · data models F1 | 1.000 | 25 | 1.000 | +0.000 | ≥ 1.0 ✅ |
| Graph · ORM models recall | 1.000 | 4 | 0.500 | +0.500 | ≥ 1.0 ✅ |
| Graph · import edges precision | 1.000 | 100 | 1.000 | +0.000 | ≥ 1.0 ✅ |
| Graph · import edges recall | 0.990 | 100 | 0.900 | +0.090 | ≥ 0.99 ✅ |
| Readiness · rule precision | 1.000 | 17 | 0.882 | +0.118 | ≥ 1.0 ✅ |
| Readiness · rule recall | 0.941 | 17 | 0.882 | +0.059 | ≥ 0.94 ✅ |
| Readiness · rule false-positive rate | 0.000 | 17 | 0.038 | -0.038 | ≤ 0.0 ✅ |
| Readiness · location precision | 0.667 | 18 | 0.857 | -0.190 ⚠️ | ≥ 0.85 ❌ |
| Readiness · location recall | 0.889 | 18 | 0.667 | +0.222 | ≥ 0.88 ✅ |
| Impact · affected modules precision | 1.000 | 27 | 1.000 | +0.000 | ≥ 1.0 ✅ |
| Impact · affected modules recall | 1.000 | 27 | 0.926 | +0.074 | ≥ 1.0 ✅ |
| Impact · routes precision | 1.000 | 38 | 1.000 | +0.000 | ≥ 1.0 ✅ |
| Impact · routes recall | 1.000 | 38 | 0.868 | +0.132 | ≥ 1.0 ✅ |
| Impact · tests precision | 1.000 | 10 | 1.000 | +0.000 | ≥ 1.0 ✅ |
| Impact · tests recall | 1.000 | 10 | 1.000 | +0.000 | ≥ 1.0 ✅ |
| Retrieval · evidence span recall | 0.608 | 20 | 0.550 | +0.058 | ≥ 0.6 ✅ |
| Retrieval · MRR | 0.353 | 20 | 0.307 | +0.046 | ≥ 0.35 ✅ |
| Retrieval · hit@5 | 0.500 | 20 | 0.450 | +0.050 | ≥ 0.5 ✅ |
| Retrieval · snippet precision | 0.124 | 20 | 0.115 | +0.009 |  |
| Q&A · structured output valid | 1.000 | 27 | 1.000 | +0.000 | ≥ 1.0 ✅ |
| Q&A · citation validity (path/lines exist) | 1.000 | 24 | 1.000 | +0.000 | ≥ 1.0 ✅ |
| Q&A · citation faithfulness (cites labelled evidence) | 0.140 | 20 | 0.132 | +0.008 |  |
| Q&A · citation recall | 0.512 | 20 | 0.463 | +0.048 |  |
| Q&A · key-fact recall (AI answers) | — | 0 |  |  |  |
| Q&A · deterministic accuracy (AI answers) | — | 0 |  |  |  |
| Q&A · abstains when unanswerable (AI) | — | 0 |  |  |  |
| Q&A · false abstention rate (AI) | — | 0 |  |  |  |
| Judge · correctness (GEval) | — | — |  |  |  |
| Judge · faithfulness | — | — |  |  |  |
| Judge · answer relevancy | — | — |  |  |  |

## Graph accuracy per repository

| Repo | Routes P / R | Route line acc. | Data models P / R | ORM models P / R | Import edges P / R | verified share |
|---|---|---:|---|---|---|---:|
| shop_api | 1.000 / 1.000 | 1.000 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 |
| clean_service | 1.000 / 1.000 | 1.000 | — / — | — / — | 1.000 / 1.000 | 1.000 |
| fastapi_template | 1.000 / 1.000 | 1.000 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 0.987 | 1.000 |

Misses (`-` expected but not found, `+` found but not expected):

- **fastapi_template · internal_imports**: - ('backend/app/alembic/env.py', 'backend/app/models.py')

## Readiness findings per repository

| Repo | Rules assessed | TP | FP | FN | TN | Location P / R |
|---|---:|---:|---:|---:|---:|---|
| shop_api | 25 | 13 | 0 | 1 | 11 | 1.000 / 0.923 |
| clean_service | 25 | 1 | 0 | 0 | 24 | — / — |
| fastapi_template | 20 | 2 | 0 | 0 | 18 | 0.333 / 0.800 |

- **shop_api**: rule errors {'SEC-HARDCODED-SECRET-DEFAULT': 'FN'}; location FP none; location FN ['SEC-HARDCODED-SECRET-DEFAULT app/core/config.py:5']
- **fastapi_template**: rule errors none; location FP ['SEC-UNAUTH-MUTATION backend/app/api/routes/login.py:45', 'SEC-UNAUTH-MUTATION backend/app/api/routes/login.py:100', 'SEC-UNAUTH-MUTATION backend/app/api/routes/users.py:54', 'SEC-UNAUTH-MUTATION backend/app/api/routes/users.py:81', 'SEC-UNAUTH-MUTATION backend/app/api/routes/users.py:103', 'SEC-UNAUTH-MUTATION backend/app/api/routes/users.py:132', 'SEC-UNAUTH-MUTATION backend/app/api/routes/users.py:182', 'SEC-UNAUTH-MUTATION backend/app/api/routes/users.py:214']; location FN ['SEC-UNAUTH-MUTATION backend/app/api/routes/private.py:23']

## Change impact per scenario

| Case | Repo | Modules P / R | Routes P / R | Tests P / R |
|---|---|---|---|---|
| shop-i1 | shop_api | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| shop-i2 | shop_api | 1.000 / 1.000 | 1.000 / 1.000 | — / — |
| clean-i1 | clean_service | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| ft-i1 | fastapi_template | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| ft-i2 | fastapi_template | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |

## Retrieval and Q&A per question

| Question | Answerable | Retrieved | Span recall | Hit@5 | Answer source | Confidence | Cites valid | Cites labelled evidence | Key facts | Judge (corr / faith / rel) |
|---|---|---:|---:|---|---|---|---:|---:|---:|---|
| shop-q1 | yes | 8 | 0.000 | no | retrieval_only | low | 1.000 | 0.000 | — | — |
| shop-q2 | yes | 11 | 1.000 | yes | retrieval_only | low | 1.000 | 0.333 | — | — |
| shop-q3 | yes | 3 | 1.000 | yes | retrieval_only | low | 1.000 | 0.333 | — | — |
| shop-q4 | yes | 7 | 1.000 | yes | retrieval_only | low | 1.000 | 0.167 | — | — |
| shop-q5 | yes | 1 | 0.000 | no | retrieval_only | low | 1.000 | 0.000 | — | — |
| shop-q6 | yes | 6 | 1.000 | yes | retrieval_only | low | 1.000 | 0.167 | — | — |
| shop-q7 | yes | 9 | 0.500 | no | retrieval_only | low | 1.000 | 0.167 | — | — |
| shop-q8 | yes | 3 | 1.000 | yes | retrieval_only | low | 1.000 | 0.333 | — | — |
| shop-u1 | no | 8 | — | — | retrieval_only | low | 1.000 | — | — | — |
| shop-u2 | no | 0 | — | — | retrieval_only | low | — | — | — | — |
| shop-u3 | no | 0 | — | — | retrieval_only | low | — | — | — | — |
| clean-q1 | yes | 5 | 1.000 | yes | retrieval_only | low | 1.000 | 0.400 | — | — |
| clean-q2 | yes | 7 | 1.000 | yes | retrieval_only | low | 1.000 | 0.167 | — | — |
| clean-u1 | no | 2 | — | — | retrieval_only | low | 1.000 | — | — | — |
| ft-q1 | yes | 12 | 1.000 | yes | retrieval_only | low | 1.000 | 0.167 | — | — |
| ft-q2 | yes | 12 | 0.000 | no | retrieval_only | low | 1.000 | 0.000 | — | — |
| ft-q3 | yes | 11 | 0.500 | yes | retrieval_only | low | 1.000 | 0.167 | — | — |
| ft-q4 | yes | 12 | 0.000 | no | retrieval_only | low | 1.000 | 0.000 | — | — |
| ft-q5 | yes | 12 | 1.000 | no | retrieval_only | low | 1.000 | 0.000 | — | — |
| ft-q6 | yes | 8 | 1.000 | yes | retrieval_only | low | 1.000 | 0.333 | — | — |
| ft-q7 | yes | 12 | 1.000 | no | retrieval_only | low | 1.000 | 0.000 | — | — |
| ft-q8 | yes | 2 | 0.000 | no | retrieval_only | low | 1.000 | 0.000 | — | — |
| ft-q9 | yes | 12 | 0.167 | no | retrieval_only | low | 1.000 | 0.000 | — | — |
| ft-q10 | yes | 12 | 0.000 | no | retrieval_only | low | 1.000 | 0.000 | — | — |
| ft-u1 | no | 9 | — | — | retrieval_only | low | 1.000 | — | — | — |
| ft-u2 | no | 2 | — | — | retrieval_only | low | 1.000 | — | — | — |
| ft-u3 | no | 0 | — | — | retrieval_only | low | — | — | — | — |

## Latency, tokens, cost, errors

| Stage | n | mean s | p50 s | p95 s | max s |
|---|---:|---:|---:|---:|---:|
| Ingest + parse + graph (per repo) | 9 | 0.138 | 0.074 | 0.305 | 0.305 |
| Retrieval (per question) | 81 | 0.017 | 0.015 | 0.034 | 0.039 |
| Answer (per question) | 81 | 0.003 | 0.003 | 0.005 | 0.020 |
| Impact (per scenario) | 15 | 0.004 | 0.003 | 0.006 | 0.006 |

SUT LLM calls: 0 (errors 0 ) · input tokens 0 · output tokens 0 · estimated cost 0.000 USD (no tokens used).

## Reproducibility

Deterministic outputs (graph, readiness, impact, retrieval) identical across 3 repeat(s): yes.
Retrieval aggregates per repeat: #0 span recall 0.608, MRR 0.353, hit@5 0.500; #1 span recall 0.608, MRR 0.353, hit@5 0.500; #2 span recall 0.608, MRR 0.353, hit@5 0.500.
Answers over 27 questions: identical text 1.000, identical citation sets 1.000, consistent abstention 1.000.

## How to read these numbers

- Scores are computed against hand-labelled ground truth in `backend/evals/benchmarks/v1/` (labels verified against the source by the maintainers, not independently reviewed). The benchmark is small (3 repositories); treat scores as regression signals and diagnostics, not as general accuracy claims.
- Precision is only reported where the label set is exhaustive. Graph and impact labels use file-level static-dependency semantics (see the metric definitions in docs/evaluation/AI_EVALUATION.md).
- Judge scores (if present) come from an LLM and inherit its biases; they are reported next to, never instead of, the deterministic metrics.
