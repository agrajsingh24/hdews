# HDEWS test plan

## Layers and where they live

| Layer | Location | What it proves |
|---|---|---|
| Risk-engine unit & boundary tests | `backend/tests/test_risk_engine.py`, `test_risk_engine_boundaries.py` | Every demo threshold below/at/above; tier boundaries; 12 safety invariants; 4,000 seeded randomised cases (single- and multi-sensor outages) |
| Feature extraction | `test_features.py` | Rolling windows, coverage, duplicates across origins, conflicts, out-of-order input, NaN/∞, usable-freshness, recovery, maintenance |
| Authentication & RBAC | `test_auth_rbac.py` | Login per role, bad/missing credentials, expiry, logout, disabled accounts, hashed tokens, rate limit, timing, role × endpoint matrix with no-mutation checks |
| API contract | `test_api.py`, `test_api_contract.py` | Methods (405), unknown routes (404), JSON errors, body limit, pagination bounds and schema, empty results, unicode, error shape, no leakage, config and scenario validation |
| Ingestion | `test_ingestion.py` | Keys, sources, NaN/∞, units, unknown fields, types, ranges, timestamps, idempotency, reordering, batch limits, scope, rate limit, mid-batch DB failure, concurrency |
| Alert lifecycle | `test_alerts_lifecycle.py`, `test_workflow.py` | Full 4 × 4 transition matrix, validation, re-open refusal, dedup, DB-level uniqueness, concurrent creation, rollback on failure, evidence linkage, data-gap separation, action ordering |
| Audit chain | `test_audit_chain.py` | Hash/link computation, append-only triggers, tampering (first/middle/last), deletion, truncation, reorder, forged insert, re-linked deletion, duplicates, rollback, concurrent writers, restart |
| Database | `test_db.py` | Fresh init, idempotent migrations, upgrade from 001 with data, failed-migration rollback, FK/CHECK/UNIQUE constraints, seed refusal, production guards, restart persistence, reset safety, atomicity |
| Simulator | `test_simulator.py` | Every preset's tiers, ordering/alignment/labels, determinism, observed data never touched, atomicity, tick without duplicates over 6 h, outage persistence, recovery only on new data |
| Explanations | `test_explanations.py` | Template fallback, every provider failure mode, grounding, tier contradictions, length, injection, evidence-only prompt, caching |
| Security | `test_security.py` | Headers, CORS, production lock-down, no network contact, secrets hygiene, XSS sinks, path traversal |
| ML harness | `test_ml_harness.py` | Temporal/geographic splits, hand-checked metrics, reproducibility, invalid datasets, leakage guard, imbalance, recording, model registration guard |
| Browser E2E | `e2e/run_e2e.py` + `e2e/scenarios.js` | Scenarios A–G on a real server, plus UI-wide checks (routes, filters, errors, a11y, IST rendering, mobile overflow, focus, dialogs, badge freshness) |
| Second-pass regressions | `test_regressions_round2.py`, `test_risk_engine_boundaries.py::test_property_simultaneous_outages_never_assert_low` | Upgrade keeps gateways working, per-source idempotency, no mixing of origins (engine, chart, overview), true receipt times after downtime, total-outage data-gap alert without alert spam, combined multi-sensor outages (1,000 randomised cases) |
| Coverage | `scripts/coverage_report.py` | Stdlib line + bytecode-branch coverage per critical module (line figures cross-checked against the stdlib `trace` module: identical) |
| Performance smoke | `scripts/perf_smoke.py` | Latency, concurrency, statement counts and query plans on a 30-day dataset |

## End-to-end scenarios (browser)
- **A Normal operation:** clean DB, seed, analyst signs in; overview, map (mouse and keyboard), site detail, units, IST times, accessibility audit.
- **B Increasing landslide risk:** simulator → HIGH → candidate alert → reviewer acknowledges (dialog focus, Escape), records action, resolves (empty reason blocked) → UI/API status agree → audit verifies.
- **C Flash flood:** river scenario → HIGH flash-flood alert; re-apply → no duplicate; evidence is flood-specific.
- **D Sensor outage:** reliability poor, offline sensors marked "not current", no LOW tier, data-gap alerts separate; recovery only after gateway readings arrive; observed and simulated readings drawn as separate lines with the mixing disclosed; a total blackout at another site raises a data-gap alert.
- **E Unauthorised actions:** viewer UI has no controls; direct API mutations → 403; database unchanged.
- **F Restart:** server restarted on the same DB; alert, ordered actions and audit chain persist; telemetry resumes.
- **G Production:** demo routes 404, simulator hidden, no demo-password hint.

## Principles
- Each fixed defect has a regression test, and the new tests were run against the baseline to show they detect the original behaviour (`docs/evidence/`).
- Tests use isolated in-memory or temporary SQLite databases only; nothing touches `backend/hdews.db`.
- Time-dependent tests pin the clock (`clock.set_frozen_now`).
- Coverage is diagnostic, not a target. Uncovered critical lines were reviewed individually, and one of those reviews found a real defect (HDEWS-025).

## Not covered (and why)
- PostgreSQL runtime: the driver is unavailable (one test reports `SKIPPED` for this).
- Live LLM provider, real data sources, field hardware: credentials/hardware needed.
- Frontend unit tests: no JS test framework is installable offline; the frontend is covered by strict `tsc` and the browser E2E suite.
- Contrast ratios: checked by design tokens and screenshots, not by an automated contrast tool.
