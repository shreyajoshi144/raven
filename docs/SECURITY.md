# Security model

## Controls implemented (and where they are tested)
| Area | Control |
|---|---|
| Passwords | Argon2id; constant-time-ish login (dummy hash for unknown users); generic error message; password min 10 chars |
| Sessions | random 256-bit token, only its SHA-256 stored; HttpOnly + SameSite=Lax (+Secure in production); server-side revocation on logout; TTL |
| CSRF | per-session HMAC token in `X-CSRF-Token` (double-submit) on every authenticated mutation, plus `Origin` same-host check |
| AuthZ | every analysis route resolves the job through an ownership check; foreign or unknown ids both return 404; nested node/file ids are verified to belong to the analysis |
| Internal API | separate service secret (`INTERNAL_SERVICE_SECRET`), constant-time compare, refuses requests with an `Origin` header; session cookies do not work there. **Do not expose `/internal/` through your public proxy** |
| n8n webhooks | `X-Raven-Webhook-Secret` (`N8N_WEBHOOK_SECRET`, different from the internal secret); UUID validation of ids |
| Input | strict GitHub URL canonicalization (https, exact host `github.com`, no userinfo/port/query/fragment/encoding/extra path, ASCII only); pydantic `extra=forbid`; 64 KiB body cap (streamed) |
| SSRF | GitHub traffic only to `api.github.com` and `codeload.github.com`; redirects followed manually (max 3) and host-checked; GitHub token is never sent to the redirect host; user input never becomes a URL host |
| Untrusted repo content | never executed/imported; archive streamed with decompression-size cap, path-safety checks, no symlink/hardlink following; binary/generated/vendored/secret files excluded |
| Secrets | redaction before storage; secret-bearing files excluded from AI context; `.env` never stored; env var *values* never recorded; logs redact tokens/keys and never contain prompts or source text |
| Prompt injection | repo text is delimited as untrusted data with an explicit system-level guard; the model has no tools; outputs are schema-validated and citations are checked against the supplied evidence; model output cannot trigger any action |
| Output encoding | frontend builds DOM with `textContent`; Markdown renderer has no HTML passthrough and allow-lists link targets; Mermaid runs in `strict` mode with server-sanitized labels |
| Headers | CSP (`script-src 'self'`, no inline/eval scripts, `object-src 'none'`, `frame-ancestors 'none'`), `nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, HSTS in production, `no-store` on API responses |
| Abuse | DB-backed rate limits: login (per IP+email and per IP), registration, analysis submission, docs regeneration, chat; per-user, per-route request limits; per-user daily quotas (analyses, questions, tokens, spend) |
| Administration | `role = admin` is set only by the server-side CLI; every admin route re-checks it; the abuse switch revokes all sessions and blocks sign-in; admin mutations are written to an append-only audit table; admins cannot disable themselves or other admins |
| Config | production refuses to start with missing/short/placeholder/duplicate secrets, insecure cookies, or a non-official GitHub host |
| Containers | non-root user, no published DB port, n8n editor bound to localhost |

## Added: account recovery and two-factor
| Area | Control |
|---|---|
| Email verification | single-use random token (256-bit, SHA-256 stored, 60-minute expiry); optional enforcement before any session is issued; resend and verify are rate limited and never reveal whether an account exists |
| Password reset | single-use emailed link; weak passwords do not burn the token; success revokes **all** sessions; forgot-password answers identically for unknown emails and is limited per IP and per email |
| TOTP 2FA | RFC 6238 (checked against the RFC test vector), +-1 step window, last accepted step stored so a code cannot be replayed; the second step uses a 5-minute single-use token limited to 5 attempts; 8 hashed single-use recovery codes shown once; disabling needs password and a code |
| Tests | `backend/tests/test_accounts.py` (15 tests) |

## Prompt injection
Repository text is delimited as untrusted data, the model has no tools, output is schema-validated and citations are checked against the supplied evidence (tested in `test_injection.py`). A hostile-repository suite (`python -m evals injection`) measures whether planted instructions are obeyed; **it has not been run against a live model**. An obedient answer that cites real evidence is not stopped by validation; that is what the suite measures.

## Known limits of the controls
* Read-route rate limits are counted in memory per API process; write limits are shared through PostgreSQL. Quotas ignore PR-review tokens.
* `/internal/v1/metrics` is protected by the service secret and the public proxy, not by network policy alone; keep it unscraped from the internet.
* Secret screening is **best-effort pattern matching**; it will miss unusual secret formats in public repos.
* `style-src 'unsafe-inline'` is required because Mermaid injects `<style>`; scripts remain strict.
* n8n workflows read the two service secrets from the n8n process environment (`N8N_BLOCK_ENV_ACCESS_IN_NODE=false`), so anyone with n8n editor access can read them. Keep the editor private and restrict who can log in to it.
* Rate-limit identity for anonymous endpoints is the socket/forwarded client IP; run behind a proxy you control and set `--forwarded-allow-ips` appropriately.
* No SMS/WebAuthn factors; TOTP only. Email delivery depends on your SMTP provider; there is no bounce handling. Accounts are not locked after repeated wrong passwords (rate limits apply instead).
