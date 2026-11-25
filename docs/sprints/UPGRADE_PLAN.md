# Three-sprint upgrade (S8–S10): plan and evidence

> Numbering: this upgrade was planned as "Sprint 1–3"; in the delivery history ([SPRINTS.md](SPRINTS.md)) they are **S8, S9 and S10**.

## Audit (what already existed)
| Area | Already in the repo | Gap for this upgrade |
|---|---|---|
| Retrieval | exact symbol/path, PostgreSQL FTS, graph neighbours, optional embeddings | channels not separable; no symbol/commit on results |
| Evidence graph | typed nodes/edges, `verified_static\|inferred\|unresolved`, source locations, unique `(analysis, key)` constraints | none found |
| Commit awareness | every analysis pinned to `commit_sha`; artifacts keyed by analysis, so a new commit is a new analysis | answers/findings did not carry the SHA themselves |
| Incremental | none: every analysis re-fetched and re-parsed everything | diff, reuse, full-reindex recovery |
| Tenancy | `OwnedJob` ownership checks on every analysis route | no cross-tenant test matrix; reuse across users must be impossible |
| Degradation | retrieval-only answers, non-fatal embeddings | not tested end to end without LLM + embeddings |

## Plan
- **S8 (planned Sprint 1) — Intelligence foundation (done, below).**
- **S9 (planned Sprint 2) — Architecture intelligence (done):** snapshot per analysis (modules, import edges, complexity per file), drift between two commits of one repository (new/removed dependencies, import cycles, coupling, layer-boundary violations, complexity growth), history timeline, predictive impact from the existing impact engine extended to routes/tests/breaking changes. Reuses `analysis_files.facts`, `code_edges`, and `incremental.diff_files`.
- **S10 (planned Sprint 3) — PR intelligence and evaluation (done):** GitHub PR fetch (compare API already used by impact), risky-change/missing-test/boundary rules over the Sprint 2 drift, evidence-cited review comments, benchmark extension and cost/latency tracking on the existing `backend/evals` harness.

Each sprint waits for approval.

## S8 — what changed
| Criterion | Implementation | Evidence (test in `backend/tests/test_sprint1.py` (the S8 tests) unless noted) |
|---|---|---|
| Hybrid retrieval, independent channels | `retrieve(..., channels={"lexical","semantic","graph"})`; each evidence item has `channel`, `symbol`, `commit_sha`, path, lines | `test_retrieval_channels_work_independently_and_carry_provenance`; semantic/lexical fallback: `test_embeddings_retrieval.py` |
| Evidence graph without duplicates | unchanged builder; unique constraints; rebuilt from all facts on every run | `test_incremental_indexing_across_commits` (distinct keys == rows; incremental graph == from-scratch graph), `test_repeated_submission_creates_no_duplicates` |
| Commit-aware answers/findings | `chat_messages.commit_sha` (migration 0005, back-filled); citations, readiness findings carry it | `test_answers_and_findings_record_their_commit` (two commits, old answers untouched) |
| Incremental indexing | `services/incremental.py`: added/modified/deleted/renamed diff against the owner's latest READY analysis; unchanged files reuse parsed facts, unchanged nodes reuse embeddings (same model only); stored in `summary.incremental`, `summary.parse.reused_from_base` | `test_diff_detects_…`, `test_incremental_indexing_across_commits` |
| Full reindex | `POST /api/v1/analyses/{id}/reindex` (READY or FAILED, owner only) ignores any base | same test: mode `full`, `reused_from_base == 0`, identical graph |
| Tenant isolation | base analysis chosen per owner; 11 endpoints × other user → 404 | `test_cross_tenant_access_is_denied_everywhere`, `test_incremental_base_is_never_another_users_analysis` |
| Failure consistency | graph delete+insert is one transaction | `test_failed_reindex_leaves_previous_graph_intact` |
| Degradation | no LLM + no embeddings: analysis, readiness, retrieval-only cited answers; no source text in logs | `test_no_llm_no_embeddings_still_analyzes_retrieves_and_labels_answers` |

### Schema, API, configuration
- Migration `0005_commit_sha_on_answers`: `chat_messages.commit_sha varchar(40)`, back-filled from `analysis_jobs`. Downgrade drops the column. No data is deleted.
- API additions (existing endpoints keep their contracts): `commit_sha` on chat messages, citations, readiness and each finding; `symbol` on retrieval-only citations; `summary.incremental` on `GET /analyses/{id}`; new `POST /analyses/{id}/reindex`.
- No new configuration. Embedding reuse requires the same `EMBEDDINGS_MODEL` as the base analysis.

### Limitations (honest)
- Incremental reuse saves parsing and embedding work; the graph, readiness and retrieval index are always rebuilt from all facts (chosen for consistency). Fetching still downloads the full archive.
- Base = latest READY analysis of the same repository by the same user at a different commit; it need not be the parent commit.
- A rename is detected only for identical content with an unambiguous pair; renamed-and-edited files appear as added + deleted. Renamed files are re-parsed because facts are path-keyed.
- Impact reports do not yet carry `commit_sha` (they belong to the analysis, which is pinned). Python and the already-supported web files only; other languages are not parsed.
- Semantic retrieval quality has not been measured; embeddings were only run against a fake embedder. Tenant isolation is application-level (ownership checks), not PostgreSQL row-level security.
- Not run: real GitHub, real LLM/embeddings endpoint, load/concurrency tests, the Docker stack with migration 0005.

---

## S9 — Architecture intelligence (implemented)
No schema change and no new configuration: snapshots are computed on demand from each analysis's stored graph and facts, so every past analysis already has history.

| Requirement | Implementation (`backend/app/services/architecture.py`) | Evidence (`backend/tests/test_architecture.py`) |
|---|---|---|
| Per-commit snapshot | modules, internal imports, external deps, cycles (iterative Tarjan), layer violations, fan-in/out, per-module cyclomatic complexity, routes, public symbols | `test_snapshot_reports_cycles_and_violations_with_evidence`, `test_cycle_detection_is_iterative_and_exact` (5,001-module cycle, no recursion) |
| Drift across commits | new/removed external dependency, new/resolved cycle, new boundary violation, coupling increase, complexity growth, new route | `test_drift_detects_…`, `test_coupling_and_complexity_growth_are_flagged_only_past_thresholds`, `test_no_drift_between_identical_content_and_no_prior_analysis` |
| Evolution history | `GET /analyses/{id}/architecture/history`: oldest-first metrics + deltas for the owner's READY analyses of the repository | `test_history_is_ordered_with_deltas_and_old_commits_unchanged` |
| Predictive impact | reverse-import closure (depth 3) of modified/deleted modules on the base graph → affected modules, routes, tests, and breaking-change users (a dependent is listed only if it imports the module **and** its text references the symbol) | `test_predicted_impact_lists_dependents_tests_and_symbol_users_with_evidence` (an unreferenced removed symbol yields no invented victims) |
| Breaking changes | removed public function/method, changed parameter list (removed params = high), removed route | same tests |
| Evidence | every finding cites `{path, start_line, end_line, commit_sha}`; `resolution` is `verified_static` or `inferred` (boundary rules) | asserted per finding |
| Tenant safety | all three endpoints use `OwnedJob`; `?base=` must be the caller's own READY analysis of the same repository | `test_explicit_base_must_be_owned_and_same_repository` |

API: `GET /api/v1/analyses/{id}/architecture`, `/architecture/history`, `/architecture/drift[?base=<analysis_id>]`. UI: new **Architecture** tab (evolution table, drift findings with evidence links, predicted impact, limitations).

Thresholds (constants at the top of the module): coupling = +3 internal imports and ≥ 8 total; complexity = +10 and +25 % on one module. Layers by directory name: api/routes/routers/endpoints/views/controllers → services → models/db/repositories/crud → core/config/utils/common; a module importing a higher layer is flagged.

### Limitations
- Heuristics, not truth: layer rules rely on directory names; repos without those names get no boundary findings. Thresholds are defaults, not tuned on real data.
- "Previous" is the owner's latest earlier analysis, not the git parent; use `?base=` to choose. Both commits must already be analyzed (READY).
- Signature drift compares parameter names only (not types or defaults); a moved or renamed module appears as removed symbols. Class and attribute changes, and non-Python code, are not diffed.
- History recomputes each snapshot per request (≤ 50 points, a handful of queries each); not cached, not load-tested.
- Predicted impact is static and bounded (depth 3, 60 items per list); it is not validated against real regressions and runs no tests.
- Not run: the Docker stack or browser UI with these endpoints, real repositories' drift, the Architecture tab visually.

---

## S10 — PR intelligence and evaluation (implemented)
Schema: migration `0006` adds `pr_reviews` and `chat_messages.input_tokens / output_tokens / latency_ms` (nullable; nothing deleted). Configuration: optional `LLM_PRICE_INPUT_PER_MTOK`, `LLM_PRICE_OUTPUT_PER_MTOK`.

| Requirement | Implementation | Evidence |
|---|---|---|
| GitHub PR integration | `POST /api/v1/pr-reviews {url}` (strict `…/pull/<n>` URL) reads the PR's base/head commits, analyses both (reusing existing analyses and incremental indexing), `GET /pr-reviews/{id}` computes the review once both are READY; `/markdown`, list; fork PRs refused | `tests/test_pr_review.py` (end-to-end, idempotency, fork/unknown/failed, URL strictness) |
| Risky changes, missing tests, architectural violations | drift findings (S9) + new readiness findings in changed files + sensitive-path changes (inferred) + changed modules with no importing/name-matched test | `test_pr_review_end_to_end_with_evidence`, `test_clean_pr_has_no_findings` |
| Evidence-backed review comments | one templated comment per finding, with path, line, side (base/head), commit and verified/inferred label; asserted to cite existing files/lines. Not posted to GitHub | same + markdown view |
| Real-codebase benchmark | `python -m evals pr`: 7 labelled scenarios, 5 of them mutations of the vendored real `fastapi/full-stack-fastapi-template` backend. Scores expected-finding recall, forbidden findings, evidence validity, reproducibility | run below; `tests/test_evals_pr.py` (harness can fail) |
| Q&A quality metrics | already in the v1 benchmark (27 questions): correctness, citation precision/recall, evidence coverage, unsupported claims, retrieval relevance, abstention; unchanged | `docs/evaluation/AI_EVALUATION.md` |
| Latency, tokens, failures, cost | every AI answer stores tokens and latency; `GET /analyses/{id}/usage` aggregates Q&A (p50/p95, failures by code, answer sources) and guide generation; cost only when prices are configured (otherwise `null` with the reason). Eval harness already tracked these offline | `test_usage_*` |

Measured on this machine (offline, fakes only): `python -m evals pr` → 7/7 cases, expected-finding recall 1.0 (9 of 9 labelled expectations), 0 forbidden findings, 0/14 invalid evidence, 7/7 reproducible across two runs.

### Limitations
- The PR suite is 7 hand-labelled cases written by the same team as the engine: a regression check, not an accuracy estimate. Precision outside the listed forbidden kinds, and behaviour on large or messy real PRs, are unmeasured.
- Review quality depends on both commits being analysable within Raven's limits; truncated analyses make drift incomplete (the analysis `partial` flag is not yet surfaced in the PR view).
- No GitHub write access: comments are not posted, no status checks, no webhooks (a user must submit the PR URL). Forks, private repositories and non-Python-only PRs are out of scope. Two analyses per PR count against the hourly analysis rate limit.
- "Sensitive area" is a filename heuristic. "Untested" ignores real coverage. Predicted impact is static and bounded.
- Q&A accuracy against a live model has still never been evaluated here. Cost figures are only as good as the prices you configure; no cost is shown for guide generation unless the same prices are set (it reuses them), and answers created before migration 0006 have no usage data.
- Not run: real GitHub PRs, the Docker stack/browser UI for the PR page, load or concurrency tests.
