# Release readiness

| | |
|---|---|
| Version / date | 1.0 · 2026-11-25 |
| Related | [QA report](08-QA-REPORT.md) · [Risk register](06-RISK-REGISTER.md) · [Deployment](../DEPLOYMENT.md) |

Two releases are assessed: **A, the public repository and local demonstration** (what exists today), and **B, a hosted public instance** (not yet built). ✅ done and evidenced · ⚠️ partly done · ⬜ not done.

## Release A: public repository and local demonstration
| Area | Check | Status | Evidence |
|---|---|:-:|---|
| Functionality | All Must and Should requirements delivered | ✅ | [Traceability](09-TRACEABILITY-MATRIX.md) |
| Quality | 490 tests pass; lint clean; benchmark 22 of 22 | ✅ | [QA report §3](08-QA-REPORT.md) |
| Quality | No high-severity defect open | ✅ | [Defect log](08-QA-REPORT.md#6-defect-log) |
| Build | Image builds from scratch | ✅ | 2026-11-25, exit 0 |
| Data safety | Backups before migrations; migrations reversible | ✅ | Dumps before `0005`, `0007`, `0008` |
| Security | Strict CSP and headers; CSRF; SSRF-safe; no code execution; secrets never committed | ✅ | `test_security_api.py`; secret scan of the repository found no real secrets |
| Documentation | Complete, consistent, checked by script | ✅ | `scripts/check_docs.py` |
| Repository | Connected to GitHub; no licence file by decision | ✅ | [D-14](07-DECISION-LOG.md) |
| CI | Green run recorded | ⚠️ | First run failed at lint; fixed in `1021a57`; push and confirm (B-02) |
| AI | One successful live answer | ⬜ | Blocked: no LLM credit (B-01) |
| Usability | Tested with real users | ⬜ | B-09 |

**Decision for Release A: GO**, with the three conditions stated honestly wherever the project is described: no live AI answer yet, CI not yet green, no user testing.

## Release B: hosted public instance
| Area | Check | Status | Notes |
|---|---|:-:|---|
| Hosting | Server, domain, HTTPS through the Caddy profile | ⬜ | B-04; the proxy config validates but no certificate has been issued |
| Secrets | Fresh production secrets; `.env` never shared | ⬜ | Generator script exists |
| Email | Real SMTP; verification and reset emails received | ⬜ | B-05 |
| Cost control | Daily quotas and spend cap set low; LLM prices configured | ⚠️ | Controls exist and are tested; values for a public instance not chosen |
| Abuse | Rate limits, abuse switch, audit trail | ✅ | `test_admin_quotas.py` |
| Observability | Health checks, logs, metrics dashboard; alerts | ⚠️ | Alerts on thresholds not built (B-06) |
| Backups | Daily dump and a restore tested | ⚠️ | Restore tested locally in S6; not on a host |
| Load | Capacity known | ⬜ | B-07 |
| Licence and policy | Licence decision; privacy statement for uploaded repository URLs | ⚠️ | No licence file; no privacy statement |

**Decision for Release B: NO-GO until** hosting, email, cost-control values and a restore test are done and recorded here.

## Rollback
Local: stop with `docker compose down` (never with `-v`, which deletes the database), restore the latest dump from `~/raven-backups`, and run `alembic downgrade -1` for a bad migration (`docker compose run --rm migrate alembic downgrade -1`).
