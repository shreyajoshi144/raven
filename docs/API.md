# API reference

All application routes live under `/api/v1`, are JSON, and return errors as `{"error": {"code", "message", "request_id", "retryable"}}` (codes are defined in `backend/app/core/errors.py`). Interactive OpenAPI docs are served at `/api/docs` outside production.

**Authentication levels**

| Level | How | Failure |
|---|---|---|
| Public | none | n/a |
| Session | `raven_session` cookie; every mutation also needs `X-CSRF-Token` and a same-host `Origin` | 401 `UNAUTHENTICATED`, 403 `CSRF_FAILED`, 403 `ACCOUNT_DISABLED` |
| Admin | session with `role = admin` | 403 `FORBIDDEN` |
| Service | `X-Internal-Secret` header, no `Origin` (n8n only; blocked at the public proxy) | 401 / 403 |

**Limits that apply to every Session/Admin route:** per-user, per-route rate limit (default 240 GET and 30 write requests per minute, `RL_READ_PER_MINUTE` / `RL_WRITE_PER_MINUTE`, answers `429 RATE_LIMITED` with `Retry-After`); daily quotas on analyses and questions (`429 QUOTA_EXCEEDED`, resets 00:00 UTC). See [ADMIN_AND_OPERATIONS.md](ADMIN_AND_OPERATIONS.md).

## Health (public)
| Method | Path | Purpose |
|---|---|---|
| GET | `/health/live` | process is up |
| GET | `/health/ready` | database reachable and migrations at head |
| GET | `/health/orchestrator` | n8n reachable |

## Accounts (public unless noted)
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/auth/register` | create an account (20 per hour per IP) |
| POST | `/api/v1/auth/login` | sign in; `mfa_required` when 2FA is on; disabled accounts get `ACCOUNT_DISABLED` |
| POST | `/api/v1/auth/login/2fa` | second step with a TOTP or recovery code |
| POST | `/api/v1/auth/verify-email`, `/resend-verification` | single-use email verification |
| POST | `/api/v1/auth/forgot-password`, `/reset-password` | single-use reset link; success revokes all sessions |
| POST | `/api/v1/auth/2fa/setup`, `/enable`, `/disable` | TOTP management (Session) |
| POST | `/api/v1/auth/logout` | revoke the session (Session) |
| GET | `/api/v1/me` | current user including `role` (Session) |

## Analyses (Session)
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/analyses` | submit a GitHub URL; pinned to a commit; reuses an identical READY analysis (`reused: true`) |
| GET | `/api/v1/analyses`, `/analyses/{id}` | list, detail with state and error |
| POST | `/analyses/{id}/retry`, `/reindex`, `/cancel` | recover, re-index incrementally, stop |
| DELETE | `/analyses/{id}` | delete the analysis and its data |
| GET | `/analyses/{id}/graph`, `/graph/flow`, `/graph/trace`, `/graph/diagram`, `/graph/nodes/{node_id}` | code graph, Map data, route trace, Mermaid, node detail with evidence |
| GET | `/analyses/{id}/map` | architecture-first map: areas, groups, files and file-to-file links |
| GET | `/analyses/{id}/readiness` | engineering-readiness findings (severity, confidence, evidence) |
| GET | `/analyses/{id}/architecture`, `/architecture/history`, `/architecture/drift` | architecture summary, snapshots, drift between commits |
| POST/GET | `/analyses/{id}/impact`, `/impact/{report_id}` | change-impact report against a branch, tag or SHA |
| GET | `/analyses/{id}/files`, `/files/{file_id}` | file list and source with line anchors |
| GET/POST | `/analyses/{id}/docs`, `/docs/download`, `/docs/generate` | onboarding guide |
| POST/GET/DELETE | `/analyses/{id}/chat` | ask a question (cited answer, `cache_hit` flag), read or clear the history |
| GET | `/analyses/{id}/usage` | token, latency and cost accounting for the analysis |
| GET | `/api/v1/status` | platform status: LLM, GitHub, orchestrator, limits |

## Pull-request reviews (Session)
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/pr-reviews` | review a same-repository PR URL against its base |
| GET | `/api/v1/pr-reviews`, `/pr-reviews/{id}`, `/pr-reviews/{id}/markdown` | list, detail, Markdown export |

## Administration (Admin)
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/admin/overview` | users, 24 h analyses by state, failures, LLM usage, cache hit rate and savings |
| GET | `/admin/users?q=&limit=` | users with today's usage against their limits |
| POST | `/admin/users/{id}/disable` `{reason}` / `/enable` | abuse switch; disabling revokes all sessions |
| PUT | `/admin/users/{id}/quotas` | per-user daily quota overrides (`null` = platform default) |
| GET | `/admin/analyses?state=` | all analyses with owner and repository |
| GET | `/admin/failures` | failed jobs with error code and failing stage, grouped by code |
| GET | `/admin/spend?days=` | tokens and cost per day and per top user |
| GET | `/admin/audit` | append-only log of admin actions |
| GET | `/admin/monitoring?minutes=` | HTTP latency/error series, job and queue health, AI latency, service health |

## Internal (Service)
`GET /internal/v1/analysis-jobs/{id}/status`, `POST .../dispatch`, `.../stage-result`, `.../complete`, `.../fail`, `POST /internal/v1/qa/retrieve`, `/qa/answer`: the n8n workflow contract (idempotent by key; see [N8N.md](N8N.md)). `GET /internal/v1/metrics` returns Prometheus text.
