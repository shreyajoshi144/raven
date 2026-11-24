# Remaining limitations (genuine)

## Not verified in the build environment
1. **Real n8n — verified on Docker (UI integration pass).** n8n 2.43.4 in Compose imported all three workflows, `publish:workflow` activated them (`n8n list:workflow --active=true` lists all three), each production webhook answers `401` without the secret, and one real analysis ran end-to-end through them (analysis workflow → worker → documentation workflow → READY; Q&A through the Q&A workflow). Still unverified against real n8n: the AI branches (no LLM key was configured, so docs were PARTIAL and Q&A retrieval-only) and long Wait/retry loops under real GitHub failures.
2. **Docker/Compose built and started** (Docker 29.7.2, macOS, arm64): migrate → api/worker/n8n healthy; `/health/live`, `/health/ready`, `/health/orchestrator` all 200. Not tested: Linux hosts, a TLS reverse proxy, restart/upgrade of existing volumes.
3. **Real LLM provider never called.** The Anthropic adapter was exercised against mock transports and a local HTTP fake; the default model id `claude-sonnet-5-5` and the `anthropic-version` header are unverified against the live API.
4. **Live GitHub REST path** (repo lookup / HEAD SHA) was exercised against fakes only; the unauthenticated quota was exhausted from this environment. Set `GITHUB_TOKEN` for realistic use.

## Product limits
5. **Static analysis only.** No runtime behaviour: dynamic imports, decorator aliases/wrappers, runtime-generated routes, dependency injection by container, reflection and monkey-patching can be missed. `calls` edges cover only statically resolvable names (not a call graph). Dynamic router prefixes (e.g. `settings.API_V1_STR`) produce *partial* paths rather than guesses.
6. **Parser runs on the Raven runtime's Python (3.12).** Files using newer syntax (e.g. Python 3.14 `except A, B:`) are reported as parse failures, and edges that depend on them are unresolved.
7. Only Python/FastAPI is modelled (other frameworks: modules/imports only). Only public GitHub repositories, default branch HEAD.
8. **Secret redaction is best-effort pattern matching**; unusual secret formats can slip through into stored source and the viewer.
9. Retrieval is lexical (Postgres FTS `simple` + exact matches + graph neighbours), not semantic; paraphrased questions may find nothing.
10. LLM budget (80 calls) applies per documentation generation, not cumulatively across regenerations. One provider only.

## Operational limits
11. Email verification, password reset and TOTP 2FA exist (2026-11-01) but real SMTP delivery and a real HTTPS domain have not been tested; no WebAuthn/SMS; registration is open unless `ALLOW_REGISTRATION=false`.
12. Rate limits key on client IP (spoofable if proxy headers are not controlled).
13. n8n workflows read the service secrets from the n8n environment, readable by anyone with n8n editor access; keep the editor private.
14. `style-src 'unsafe-inline'` is required by Mermaid. The vendored Mermaid bundle is 3.5 MB.
15. Cancellation of a running analysis is cooperative (checked between stages and during parsing).
16. No automatic data-retention expiry job; users delete analyses manually (cascades everything).
17. Not load-tested; analysis caps (2000 files, 20 MiB source, 600 s) bound per-job cost, concurrency is `MAX_CONCURRENT_ANALYSES` per worker.
18. Frontend tested only in Chromium. At 375 px the overview, Files, Ask, Health and Impact screens were checked for horizontal overflow (none); the Guide still overflows at that width (wide diagrams/tables, pre-existing). Otherwise desktop sizes only; keyboard operation and semantics are built in (landmarks, skip link, aria-live, real buttons/lists, arrow-key traversal of the flowchart, focus rings) but no automated accessibility audit was run and the narrow/mobile layout was not visually verified. Failure states use solid black plus an icon and text (no red), so contrast was checked by eye, not by a WCAG tool.
19. The Map lays out at most 200 files at once (default 70, most-connected first; narrow with the folder focus). The layered layout is a heuristic (longest-path layering + barycenter ordering): very dense graphs can have crossing edges. Edge routing is a single bezier per connection, not obstacle-avoiding.
20. Light theme only, by design (no dark mode).

## AI layer (2026-11-01)
Implemented but **never run against a real model or embeddings endpoint** (offline tests use fakes): fallback model / second provider, semantic retrieval, model + prompt versioning, and the prompt-injection suite. Specifically:
- Semantic retrieval quality is unmeasured: the benchmark has not been run with embeddings configured, and similarity is compared in Python (fine for thousands of nodes, not for very large repositories; pgvector would be the next step).
- The injection suite only exercises model behaviour in `--sut live` mode; offline it verifies the retrieval-only path and the scoring. It has 6 cases and is a regression check, not a security guarantee.
- Fallback covers availability errors only; there is no cost-aware routing and no caching.
- Prompt versioning records a hash of the prompt text; prompts are not yet stored as separately released artifacts.

## Found by the AI evaluation benchmark
Fixed, with regression tests:
- 2026-10-27:
  - unparseable newer syntax dropping whole files;
  - non-deterministic retrieval;
  - SQLModel `table=True` through a base class;
  - `os.getenv` flagged as "required at import";
  - line counts one too high.
- 2026-11-01: `SEC-UNAUTH-MUTATION` not recognising superuser dependencies or auth through `Annotated` aliases such as `CurrentUser`.

Still open:
- **Partial parsing is coarse.** Syntax newer than Python 3.12 is recovered exactly only for PEP 758 `except A, B:`. Any other unsupported statement is left out at top-level granularity (a whole function or class), and the file is reported as partially parsed.
- **Re-exported names.** `from pkg.mod import Name`, where `Name` is re-exported from a library, is not linked to `pkg/mod.py`.
- **Literal getenv fallbacks.** `SEC-HARDCODED-SECRET-DEFAULT` ignores literal `os.getenv` fallbacks.
- **Auth recognition is name-based.** It matches dependency names against a pattern (auth, current_user, superuser, token, …) and resolves `Annotated` aliases, but it does not follow what a dependency function actually checks.
- **Lexical retrieval.** Paraphrased questions miss their code.
- **AI-answer quality has not been measured** (no live-model evaluation has run).

## Added in analyzer 1.1.0 — known gaps
- Health, Impact and the Q&A confidence/inferred display now have UI. The AI-answer-with-inferred-claims rendering was verified in the browser with a stubbed response only (no LLM key); the live stack produced retrieval-only answers.
- Live GitHub compare/commits were called from the Docker stack (unauthenticated). The Anthropic API was not called.
- `backend/tests/test_workflows.py` validates the workflows statically; the GitHub Actions CI file was edited (frontend unit-test step) but never executed.
- `e2e/browser_ui_basic.py`, `browser_full_flow.py` and `palette_audit.py` were not re-run in this pass (they need Playwright and the Linux paths in `e2e/up.sh`). The new CSS uses only existing palette variables.
- Readiness is heuristic: reachability is not coverage; auth findings cannot see middleware/proxies; dependency CVEs and runtime behaviour are not assessed.
- Frontend: no bundler aliases, no framework routing/state, no URL building across files; TS/JSX are scanned as text. Impact does not trace former dependents of deleted files.
- Analyses created before 1.1.0 have no readiness data until re-run.
