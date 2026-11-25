# Traceability matrix

| | |
|---|---|
| Version / date | 1.0 · 2026-11-25 |
| Related | [PRD](02-PRD.md) · [QA report](08-QA-REPORT.md) · [Architecture](../architecture/ARCHITECTURE_AND_WORKFLOWS.md) |

Each requirement is traced to where it is implemented, the tests that prove it and its current status. Test files are in `backend/tests/` unless noted; component paths are relative to `backend/app/`. `scripts/check_docs.py` checks that every file named here exists.

**Status:** Verified = tests pass and the behaviour was observed; Partial = part verified; the reason is stated.

## Functional requirements
| ID | Requirement | Implemented in | Tests | Status |
|---|---|---|---|---|
| FR-01 | Submit a public repository | `services/github.py`, `api/routes_analyses.py`, `core/errors.py` | `test_urls.py`, `test_github_llm.py`, `test_lifecycle.py` | Verified |
| FR-02 | Run and recover the pipeline | `services/jobs.py`, `services/state.py`, `workers/`, `automation/n8n/` | `test_internal_contract.py`, `test_lifecycle.py`, `test_recovery_migrations.py`, `test_workflows.py` | Verified (also real n8n run, S2) |
| FR-03 | Evidence graph | `analysis/`, `services/flow.py` | `test_graph.py`, `test_webparse.py`, `test_archive.py`, `test_frontend_links.py`, `test_defect_fixes.py` | Verified |
| FR-04 | Interactive Map | `services/codemap.py`, `services/areas.py`; `web/src/screens/MapView.jsx` | `test_map_and_review.py`; `web/tests/shell.test.mjs` | Verified (API by tests; interaction by manual browser checks) |
| FR-05 | Onboarding guide | `services/docs_builder.py` | `test_lifecycle.py`, `test_frontend_links.py`, `test_sprint1.py` | Partial: deterministic guide verified; AI prose never produced live |
| FR-06 | Readiness findings | `analysis/readiness.py` | `test_readiness.py`, `test_defect_fixes.py`, `test_ui_contracts.py` | Verified |
| FR-07 | Change impact | `services/impact.py` | `test_impact.py`, `test_ui_contracts.py` | Verified |
| FR-08 | Cited Q&A | `services/qa.py`, `retrieval/search.py`, `services/llm.py` | `test_chat.py`, `test_qa_confidence.py`, `test_retrieval_determinism.py`, `test_llm_errors.py`, `test_llm_fallback.py`, `test_injection.py` | Partial: retrieval-only and fallbacks verified; no successful live answer |
| FR-09 | Architecture drift | `services/architecture.py` | `test_architecture.py` | Verified |
| FR-10 | Plain-language pull-request review | `services/pr_review.py`, `api/routes_pr.py`; `web/src/screens/PullRequests.jsx` | `test_pr_review.py`, `test_map_and_review.py`, `test_evals_pr.py` | Verified |
| FR-11 | Accounts and sessions | `services/accounts.py`, `services/security.py`, `api/routes_auth.py` | `test_accounts.py`, `test_security_api.py` | Partial: real email delivery untested |
| FR-12 | Admin console | `api/routes_admin.py`, `admin_cli.py`; `web/src/screens/Admin.jsx` | `test_admin_quotas.py` | Verified |
| FR-13 | Usage controls | `services/quotas.py`, `api/deps.py` | `test_admin_quotas.py`, `test_security_api.py` | Verified |
| FR-14 | Caching | `services/qa.py`, `services/embeddings.py` | `test_cache.py` | Partial: tested with fakes; never held a live answer |
| FR-15 | Monitoring | `core/metrics.py`, `api/routes_admin.py`, `api/routes_internal.py` | `test_monitoring.py` | Verified |
| FR-16 | Commit-aware and incremental analysis | `services/incremental.py` | `test_sprint1.py` | Verified |
| FR-17 | Usage and cost accounting | `services/quotas.py`, `api/routes_pr.py` (`/usage`) | `test_admin_quotas.py`, `test_llm_fallback.py` | Verified (unit level) |

## Non-functional requirements
| ID | Requirement | Where it is met | Evidence | Status |
|---|---|---|---|---|
| NFR-01 | Security | `api/middleware.py`, `api/deps.py`, `services/security.py` | `test_security_api.py`, `test_urls.py`, `test_archive.py`, `test_secrets_filters.py`, `test_config.py` | Verified by tests; no penetration test |
| NFR-02 | Reliability | `services/state.py`, `services/jobs.py`, `workers/` | `test_internal_contract.py` (9×9 transition matrix, concurrency), `test_recovery_migrations.py` | Verified |
| NFR-03 | Accuracy | `backend/evals/` | Benchmark run `27e096d5db28`, 22 of 22 gates; `test_evals_units.py`, `test_evals_smoke.py` | Verified on 3 repositories |
| NFR-04 | Performance | per-analysis caps in `core/config.py` | One recorded run: 11.3 s ([evaluation §3](../evaluation/EVALUATION_AND_RESULTS.md)) | Partial: no load test |
| NFR-05 | Honesty | labels in `analysis/`, `services/qa.py`, `services/pr_review.py` | `test_qa_confidence.py`, `test_ui_contracts.py`, `test_chat.py` | Verified |
| NFR-06 | Usability | `web/src/screens/` | Manual browser checks (QA report §5) | Partial: no usability test |
| NFR-07 | Operability | `api/routes_health.py`, `core/logging.py`, `infra/`, admin console | `test_monitoring.py`; local stack health | Verified locally |
| NFR-08 | Portability | `docker-compose.yml`, `infra/Dockerfile` | From-scratch build 2026-11-25 | Verified |
| NFR-09 | Privacy | `services/jobs.py` (`get_owned_job`), delete cascades | `test_sprint1.py` (11 endpoints × other user → 404), `test_lifecycle.py` | Verified |
| NFR-10 | Maintainability | `migrations/`, `scripts/check_docs.py`, `.github/workflows/ci.yml` | `test_recovery_migrations.py` (downgrade/upgrade), lint, documentation check | Partial: CI run not yet green |

## Coverage summary
All 17 functional and all 10 non-functional requirements have an implementation and tests; none is unimplemented. **Fully verified:** 13 functional (all except FR-05, FR-08, FR-11, FR-14) and 7 non-functional (NFR-01, 02, 03, 05, 07, 08, 09). **Partial:** FR-05, FR-08, FR-11, FR-14, NFR-04, NFR-06 and NFR-10, for the reasons in the status column.
