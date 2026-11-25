# Risk register

| | |
|---|---|
| Version / date | 1.0 · 2026-11-25 |
| Owner | Shreya Joshi |
| Related | [QA report](08-QA-REPORT.md) · [Backlog](05-PRODUCT-BACKLOG.md) · [Decision log](07-DECISION-LOG.md) |

**Scales.** Likelihood and impact: Low (L), Medium (M), High (H). Score: L=1, M=2, H=3 multiplied. **Status:** *Occurred* means the risk became real and was handled; *Mitigated* means controls exist and are tested; *Accepted* means it is known and left; *Open* needs action. Scores are the owner's judgement at 2026-11-25.

| ID | Risk | L | I | Score | Response | Status | Evidence |
|---|---|:-:|:-:|:-:|---|---|---|
| R-01 | The LLM provider is unavailable or out of credit | H | M | 6 | Fallback model support; retrieval-only answers with source locations; quota errors mapped to a clear code | **Occurred**, handled | The OpenAI account ran out of credit and Raven fell back as designed; `test_llm_errors`, `test_llm_fallback` |
| R-02 | AI answers are wrong or invented | M | H | 6 | Output schema-validated; citations must overlap supplied evidence; confidence is a rule over evidence; claims beyond the code shown as inferred | Mitigated; residual **open** | Tests with fakes; quality with a live model not measured (B-01) |
| R-03 | Prompt injection through repository text | M | H | 6 | Repository text delimited as data, no tools for the model, schema validation, injection suite | Mitigated | `test_injection`; the suite is a regression check, not a guarantee |
| R-04 | Static analysis misses dynamic behaviour | H | M | 6 | Edges labelled verified, inferred or unresolved; a fixed "not assessed" list | Accepted | [LIMITATIONS](../LIMITATIONS.md) |
| R-05 | A malicious repository attacks the platform (archive bombs, symlinks, path traversal, SSRF) | M | H | 6 | Code never executed; streamed capped archives; link and traversal checks; GitHub host allow-list | Mitigated | `test_archive`, `test_urls`, `test_github_llm` |
| R-06 | Secrets in analysed repositories are stored or shown | M | M | 4 | Pattern-based redaction before storage; secret-bearing files excluded from AI context | Accepted (best effort) | `test_secrets_filters`; redaction misses unusual formats |
| R-07 | Cost overrun once strangers can use it | M | H | 6 | Daily quotas including token and optional spend caps; answer cache; per-route rate limits | Mitigated; not tested at load | `test_admin_quotas`, `test_cache`; B-07 |
| R-08 | Abuse or spam sign-ups | M | M | 4 | Rate limits, email verification, admin abuse switch with audit trail | Partly mitigated | Real email delivery untested (B-05) |
| R-09 | One-person delivery: knowledge and availability | H | M | 6 | Documentation, tests, generated workflows, decision log | Accepted | This pack |
| R-10 | Scope creep and feature sprawl | M | M | 4 | PRD non-goals; recorded cuts | Mitigated | [PRD §6](02-PRD.md#6-what-was-cut-and-why) |
| R-11 | Documents contradict each other or the product | H | M | 6 | `scripts/check_docs.py` checks links, naming and key numbers; one source per fact | Mitigated | Check runs locally and in CI |
| R-12 | Environment failures: full disk, Docker stopped, PyPI unreachable | H | M | 6 | Backups before migrations; volumes never reset; layered image as a temporary workaround; from-scratch build later verified | **Occurred**, handled; residual open | Host disk filled during the redesign redeploy (S12) and PyPI timed out inside Docker; from-scratch build passed 2026-11-25 (B-03) |
| R-13 | Data loss during migrations | L | H | 3 | Dump before each migration; additive migrations with downgrades | Mitigated | Dumps taken before `0005`, `0007`, `0008`; `test_recovery_migrations` |
| R-14 | False alarms in pull-request review destroy trust | H | M | 6 | Review priority rewritten in plain words; removed tests and unused removals no longer "high"; proven or guess labels; "reads structure, not logic" note | **Occurred**, handled; residual | Review on a real repository disagreed with another reviewer; DEF-15, DEF-16 |
| R-15 | First-time users cannot understand the product | H | H | 9 | Architecture-first Map, plain-language review page, first-use guidance | **Occurred**, partly handled; **open** | Review feedback (S15); no usability test (B-09) |
| R-16 | The automated pipeline is not proven | M | M | 4 | CI defined for lint, tests, benchmark gate and frontend checks | **Occurred** (first run failed at lint), fixed; **open** until green | DEF-19; B-02 |
| R-17 | GitHub API rate limits | M | M | 4 | Optional token; clear error code; caching of identical analyses | Mitigated | `test_github_llm` |
| R-18 | Licence and ownership are unclear | L | M | 2 | Decision to publish with no licence file (all rights reserved) | Accepted | [D-14](07-DECISION-LOG.md) |
| R-19 | A workflow-engine fault corrupts job state | M | H | 6 | The backend owns every state transition; n8n holds no state; idempotency keys; receipts | **Occurred** once (receipts reused across analyses), fixed | DEF-14; `test_internal_contract` |
| R-20 | No hosted instance or real users: nothing proves it works outside one laptop | H | M | 6 | Release checklist; backlog B-04 | **Open** | [Release readiness](10-RELEASE-READINESS.md) |

## Summary
20 risks. Six have occurred: R-01, R-12, R-14, R-15 (only partly handled), R-16 and R-19. The highest score is R-15 (9). Items that still need action: **R-02** (live answer quality, B-01), **R-15** (usability, B-09), **R-16** (green CI, B-02), **R-20** (no hosted instance, B-04) and the residual of **R-12** (B-03).
