# HDEWS security audit

**Date:** 2026-10-28 (two passes; the second pass independently re-verified the first, see BUG_AUDIT_REPORT.md) · **Method:** source review of every module, local-only dynamic testing (pytest API tests, Playwright against a local server), `ruff` static analysis (rules E9/F/B), and reproduction of every finding on the baseline commit `5758680`. No testing touched external systems.

> HDEWS is a prototype. Passing these checks does not make it suitable for operational emergency use.

## Findings

| ID | Severity | Finding | Fix | Verification |
|---|---|---|---|---|
| HDEWS-012 | **Critical** | `HDEWS_ENV=production` seeding created admin/analyst/reviewer/viewer with the README-documented password `hdews-demo` | Demo seed refused in production; production start-up refuses any active account that verifies against a documented default password | `test_db.py::test_seed_refused_in_production`, `::test_production_refuses_to_start_with_default_passwords`; baseline evidence in `docs/evidence/repro_baseline.txt` |
| HDEWS-007 | Medium | Broken authorization on ingestion: any push-source key could write readings for every site | Per-source `ingest_site_scope` (migration 002); out-of-scope readings rejected | `test_ingestion.py::test_source_site_scope_is_enforced` (fails on baseline) |
| HDEWS-001 | High | Unvalidated input (`Infinity`) caused denial of service of `/api/overview` for all users | Non-finite JSON rejected; responses sanitised | `test_ingestion.py` NaN/Infinity tests (fail on baseline) |
| HDEWS-004 | Medium | Unbounded request bodies (memory exhaustion) | 1 MB streamed limit → 413 | `test_api_contract.py::test_body_size_limit` (fails on baseline) |
| HDEWS-013 | High | Destructive script deleted any SQLite file named by `DATABASE_URL` | Refuses non-HDEWS files, real data without `--force`, and production | `test_db.py` reset tests |
| HDEWS-016 | Medium | LLM output could contradict the rule engine's tier (e.g. obeying a prompt injection) and pass; unbounded provider calls | Tier-contradiction and length checks; per-assessment cache | `test_explanations.py` (incl. prompt-injection test; fail on baseline) |
| HDEWS-015 | Medium | Provider errors raised 500s; error text could carry request details | All provider errors fall back; only the exception type is reported | `test_explanations.py::test_any_provider_failure_falls_back` |
| HDEWS-018 | Medium | Audit-log tail truncation undetected | Sequence-contiguity + high-water-mark check; `head_hash` for external anchoring | `test_audit_chain.py` (fail on baseline) |
| HDEWS-021 | Medium | PostgreSQL chain appends not serialised (possible fork) | Advisory transaction lock | **Unverified** — psycopg unavailable |
| HDEWS-019 | Low | Username enumeration by timing | Dummy scrypt for unknown users | `test_auth_rbac.py::test_unknown_username_still_runs_password_hashing` |
| HDEWS-025 | Low | Malformed stored hash → unhandled exception (500) on login | `verify_password` never raises | `test_auth_rbac.py` (fail on baseline) |
| HDEWS-020 | Low | `LIKE` wildcard injection in search (not SQL injection; all SQL is parameterised) | Escaped patterns | `test_api_contract.py::test_search_wildcards_are_literal` |
| HDEWS-022 | Low | Data-driven URLs rendered without a scheme check (`javascript:`) | `safeUrl()` allows http(s) only | E2E check + source scan |
| HDEWS-027 | Low | Revoked token could remain in the browser after sign-out | Local session cleared before server revocation | E2E Scenario B |
| — | Low | Ingestion key comparison was not constant-time | `hmac.compare_digest` | Code review; ingestion tests |
| HDEWS-032 | Medium | Cross-source interference in ingestion: idempotency keys were global, so one push source (holding its own valid key) could pre-submit keys and cause another source's readings to be silently discarded | Keys namespaced per source (`<source_id>:<key>`), migration 005 | `test_regressions_round2.py::test_idempotency_keys_are_scoped_per_source` (failed before fix) |
| HDEWS-031 | Medium | Availability: the HDEWS-007 migration rejected every reading from existing gateways after an upgrade (fail-closed with no way to configure) | Backfill pre-upgrade scope; audited `scripts/set_ingest_scope.py` | `::test_upgrade_keeps_existing_gateway_able_to_write`, `::test_set_ingest_scope_script`; PostgreSQL 16 migration run |

## Checks with no defect found

| Area | Result | Evidence |
|---|---|---|
| Hardcoded credentials / secrets in git | None; `.env` is git-ignored; `.env.example` holds placeholders only | `test_security.py::test_no_secrets_or_databases_tracked_in_git` |
| Password storage | scrypt (n=2¹⁴, r=8, p=1), per-user salt, constant-time compare | `security.py`; tests |
| Session tokens | 256-bit random, stored as SHA-256 only, 12 h expiry, logout revokes only that session, disabled accounts lose existing sessions | `test_auth_rbac.py` (expiry, logout, hashing, disabled) |
| Server-side RBAC | Every mutating endpoint is checked on the server; a 4-role × 6-endpoint matrix is tested, and denials verified to leave the database unchanged | `test_auth_rbac.py::test_permission_matrix_enforced_server_side` (24 cases) |
| IDOR / horizontal escalation | Resources are role-scoped, not per-user (shared ops data by design); unknown or traversal-style IDs → 404 | `test_auth_rbac.py::test_no_idor_on_nonexistent_resources` |
| SQL injection | All values parameterised. Dynamic SQL is limited to fixed column-name lists (`where` built from allow-listed keys) | Code review of every `f"..."` SQL; injection-shaped IDs tested |
| XSS | The UI builds DOM with `textContent` (`h()`); no `innerHTML`/`eval`; CSP `script-src 'self'` | `test_security.py::test_frontend_has_no_html_injection_sinks` |
| CSRF | Not applicable: authentication is a bearer header, not cookies | Design |
| Session fixation / cookie flags | Not applicable: no cookies | Design |
| Security headers | nosniff, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, CSP with `frame-ancestors 'none'`, `Cache-Control: no-store` on API | `test_security.py::test_security_headers_on_api_and_static` |
| CORS | Off by default; only listed origins when configured | `test_security.py` CORS tests |
| Error leakage | Unhandled errors → generic 500; validation errors list field names, never submitted values | `test_api_contract.py::test_unexpected_exception_is_generic_500_without_internals`, `::test_validation_errors_list_fields_without_echoing_values` |
| Path traversal (static files) | Starlette `StaticFiles` blocks traversal | `test_security.py::test_static_files_do_not_allow_path_traversal` |
| Rate limits | Login 10/min/IP and ingestion 120/min/IP, both verified | `test_auth_rbac.py::test_login_rate_limit`, `test_ingestion.py::test_ingestion_rate_limit` |
| Production safeguards | Demo endpoints 404, simulator hidden, no demo-password hint, background simulated telemetry disabled | `test_security.py::test_production_mode_disables_demo_routes_and_hints`; E2E Scenario G |
| Public contact | Escalations and "test notifications" make **no network connection** (socket patched to fail during the full workflow) | `test_security.py::test_alert_actions_make_no_network_connections` |
| Outbound network code | The only outbound call in `backend/app` is the optional LLM request (`urllib`, `LLM_TIMEOUT_S` timeout, cached per assessment). No SMS/e-mail/CAP/siren code exists | `grep` of `backend/app` for `urlopen`, `requests`, `httpx`, `smtplib`, `socket` (second pass) |
| Audit immutability | DB triggers reject UPDATE/DELETE; edits, deletions, insertions, reorders and truncation detected | `test_audit_chain.py` (17 tests) |
| Secrets in API responses | No password hashes or ingest-key hashes in any response | `test_security.py::test_api_responses_never_include_password_hashes_or_ingest_keys` |
| LLM prompt | The model receives only structured evidence; API key is header-only and never logged or returned | `test_explanations.py::test_llm_receives_only_structured_evidence` |

## Residual risks (accepted for a prototype, documented)

1. **Bearer token in `sessionStorage`.** Readable by any script running in the origin. Mitigated by the strict CSP and the absence of HTML sinks, but an HttpOnly-cookie session with CSRF protection is stronger for production.
2. **Demo accounts and shared roles.** No identity provider, MFA, password policy or per-user account management. Replace before real use.
3. **Rate limiting is in-memory and keyed by client IP**, and its per-IP buckets are never evicted. It resets on restart and does not work across multiple processes. Behind a reverse proxy every client shares an IP unless forwarded headers are trusted. There is no per-account lockout.
4. **Audit tamper-evidence** detects edits, deletions, inserts, reordering and truncation. It cannot detect a privileged attacker who rewrites the *entire* chain *and* SQLite's sequence table, unless `head_hash` (returned by `/api/audit-log/verify`) is periodically recorded outside the database.
5. **Ingestion keys** are long-lived shared secrets with no rotation endpoint. Rotate by updating `ingest_key_hash` directly.
6. **No TLS termination** in the app. Deploy behind HTTPS, then add HSTS.
7. **Dependency vulnerabilities were not scanned.** `pip-audit`/`npm audit` need network access, which this environment lacks. Pinned runtime versions: starlette 1.7.0, uvicorn 0.54.0, pydantic 2.13.5. Run `pip-audit -r backend/requirements.txt` before deployment.
8. **PostgreSQL path untested** (incl. HDEWS-021).
9. **Single-node design.** The global DB lock serialises requests; heavy load degrades latency rather than correctness.

## Static analysis

`ruff 0.16.9` (from the local uv cache) with rule sets E9 (syntax), F (pyflakes) and B (bugbear) over `backend`, `ml`, `scripts`, `e2e`:
- Fixed: one unused import, three unused loop variables, five over-broad `pytest.raises(Exception)` assertions (tightened to specific exceptions with message matches).
- Remaining, accepted: B904 (`raise ... from` inside `except` in the HTTP error-translation layer). The chained exception is never sent to clients.
- Command: `ruff check --select E9,F,B --ignore B008,B905,B904 backend ml scripts e2e` → *All checks passed*.
- **Second pass (re-run, not inherited):** the same command initially reported 2 unused imports in the new `test_regressions_round2.py`. They were fixed, and the re-run printed *All checks passed!*. Without the ignores, the remaining findings are 18 × B904 and 2 × B905, all accepted as described above.

## Deployment-readiness review (third pass, 2026-10-29)

| ID | Severity | Finding | Fix | Verification |
|---|---|---|---|---|
| HDEWS-042 | High | No safe internet-facing mode: `development` on a host falls back to the published password and prints the gateway key to logs; `production` has no account bootstrap | `HDEWS_ENV=demo` with mandatory strong password and no secret output; default-password start-up guard for demo and production; audited `scripts/manage_users.py` (passwords never on the command line; password change and disable revoke sessions) | `test_deployment.py` (8 tests); local entrypoint run showed 0 password occurrences in logs |
| HDEWS-041 | Medium | Behind a platform proxy, login/ingestion rate limits were shared by all clients (one attacker could lock out every user) | `CLIENT_IP_SOURCE` (`peer`, `x-forwarded-for-first`, `x-forwarded-for-last`), with a spoofing caveat in the docs | `test_deployment.py` client-IP tests; post-deploy check in `docs/DEPLOYMENT.md` |
| HDEWS-040 | Medium | Unknown `HDEWS_ENV` silently meant `development` (fail-open) | Validated; start-up fails | `test_deployment.py::test_unknown_environment_name_is_rejected` |
| HDEWS-043 | Medium | Container ran as root and hid start-up failures | Entrypoint drops to uid 10001 with `setpriv --no-new-privs`; `start.py` exits non-zero on any refusal | Local entrypoint run (server uid 10001); CI Docker job asserts uid and refusal |
| HDEWS-044 | Low | Tests read the developer's `.env` | `HDEWS_DOTENV=0` in tests and in the image | Test suite |

**Repository secrets scan (third pass).** History (`git log --all -p`) and every file that would be committed were scanned for
private keys and AWS, GitHub, Anthropic/OpenAI and Slack token patterns, and for tracked `.env`, `.db`, `.pem` and `.key` files.
**Nothing found.** The only credentials in the repository are documented placeholders (`hdews-demo`, `change-me-*`) and
test-only values; hosted start-up refuses the placeholders. `.gitignore` covers `.env`/`.env.*` (except `.env.example`),
databases, virtualenvs, archives and editor files. `.dockerignore` keeps `.env`, databases, `.git` and tests out of the image.

**Secrets in CI/CD.** The Render deploy hook is a GitHub Actions **secret** (`RENDER_DEPLOY_HOOK_URL`). Render's docs say
the hook URL is a secret, and anyone who has it can trigger deploys. The public URL is a non-secret **variable**. Application
secrets are entered in Render (`sync: false`) and never written to `render.yaml`. The workflow has `contents: read`
permissions only, and the deploy job runs only for pushes to `main` after every other job passes.

**Remaining risks for a hosted demo.** Shared demo accounts with one password; replace them with personal accounts using
`manage_users.py`. The in-memory rate limiter resets on deploy. The header behaviour behind Render's proxy should be confirmed
after the first deploy. The dependency vulnerability scan is still not run (`pip-audit -r backend/requirements.txt` and
`npm audit` in `frontend/` need network access).
