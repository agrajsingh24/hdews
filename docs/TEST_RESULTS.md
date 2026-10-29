# HDEWS test results

**Date:** 2026-10-28 · **Environment:** Linux x86_64 (2 CPUs), Python 3.13.18, Node 22.23.4, TypeScript 7.0.2, Chromium via Playwright (pre-installed), SQLite 3.53.1, PostgreSQL 16 server (schema checks only).
Every figure below was produced by a command that actually ran in this environment. Nothing is carried over from an earlier, unverified run.

> A passing test suite shows that the software behaves as specified. It does **not** validate HDEWS as a disaster-prediction or official early-warning system: thresholds are uncalibrated and all telemetry is simulated.

## 1. Baseline (original prototype, commit `5758680`, before any change)

| Check | Command | Result |
|---|---|---|
| Backend tests | `cd backend && python -m pytest -rA` | **41 passed, 0 failed, 0 skipped** in 12.2 s |
| Frontend type-check | `cd frontend && tsc -p .` (strict) | Clean |
| Compiled assets vs source | fresh `tsc` compile diffed against `frontend/dist/js` | Identical |
| Browser walkthrough (the baseline's only browser test) | `node scripts/e2e_walkthrough.js <dir>` against a baseline server on a temporary DB | Completed; 0 console/page errors; 15 screenshots |
| Coverage | — | **Not measured**: coverage.py / pytest-cov not installable (no PyPI access) |

The baseline suite was green, but the defects listed in `BUG_AUDIT_REPORT.md` were present. That is why each fix needed a test that **fails on the baseline**.

## 2. Regression tests run against the baseline

The first audit pass's new test files were copied into a pristine baseline worktree and run there (second pass, re-measured):
**158 failed** (alerts lifecycle 1, API contract 9, audit chain 7, auth/RBAC 3, explanations 11, ingestion 11, ML harness 7, risk-engine boundaries 106, simulator 3) and 2 modules could not be imported (`test_db.py`, `test_features.py` need APIs the baseline lacks). The second pass's own regression tests (`test_regressions_round2.py`) each failed on the pre-fix tree before their fix was applied. The output is recorded in `BUG_AUDIT_REPORT.md`.

## 3. Final results (after all fixes)

| Check | Command | Result |
|---|---|---|
| Backend tests | `cd backend && python -m pytest -rs` | **468 passed, 0 failed, 1 skipped** in 107.7 s |
| Skipped test | `test_db.py::test_postgres_runtime_path_is_blocked_without_driver` | *psycopg not installed: PostgreSQL runtime path cannot be exercised* (genuine environmental block) |
| Frontend type-check | `cd frontend && tsc -p .` | Clean (strict) |
| Compiled assets vs source | `./scripts/build_frontend.sh`, then a fresh compile diffed against `dist/js` | Identical |
| Browser E2E A–G | `python e2e/run_e2e.py` | **8/8 scenarios, 93/93 checks passed** in 25.9 s (results in `e2e/results.json`) |
| PostgreSQL schema | `psql -f` migrations 001→005 on PostgreSQL 16, on a database containing rows | All applied; scope backfill and key namespacing correct; 005 idempotent on re-run |
| Static analysis | `ruff check --select E9,F,B --ignore B008,B905,B904 backend ml scripts e2e` (ruff 0.16.9 from local cache) | All checks passed |
| Defect reproductions | `python docs/evidence/second_pass_verify_claims.py <repo>` | 12 reproductions: all reproduce on baseline, all fixed now (`docs/evidence/second_pass_verification.txt`) |
| Performance smoke | `python scripts/perf_smoke.py --days 30` | See §6 |

### Backend tests by file

| File | Passed | Failed | Skipped |
|---|---|---|---|
| `test_alerts_lifecycle.py` | 33 | 0 | 0 |
| `test_api.py` | 15 | 0 | 0 |
| `test_api_contract.py` | 35 | 0 | 0 |
| `test_audit_chain.py` | 17 | 0 | 0 |
| `test_auth_rbac.py` | 65 | 0 | 0 |
| `test_db.py` | 14 | 0 | 1 |
| `test_explanations.py` | 24 | 0 | 0 |
| `test_features.py` | 17 | 0 | 0 |
| `test_ingestion.py` | 50 | 0 | 0 |
| `test_ml_harness.py` | 18 | 0 | 0 |
| `test_regressions_round2.py` | 9 | 0 | 0 |
| `test_risk_engine.py` | 15 | 0 | 0 |
| `test_risk_engine_boundaries.py` | 119 | 0 | 0 |
| `test_security.py` | 11 | 0 | 0 |
| `test_simulator.py` | 19 | 0 | 0 |
| `test_workflow.py` | 7 | 0 | 0 |
| **Total** | **468** | **0** | **1** |

Blocked (not run, so neither passed nor failed): PostgreSQL runtime path; live LLM provider; dependency vulnerability scan (`pip-audit`, `npm audit`); Docker image build; frontend unit tests (no JS test framework installable). See §7.

### End-to-end scenarios (real server, real Chromium, isolated temporary database)

| Scenario | Checks | What was exercised |
|---|---|---|
| A Normal operation | 14/14 | Seeded DB, analyst login, overview (Simulated data mode, 6 sites), IST rendering, map markers, keyboard Enter on marker opens drawer, drawer close, zoom, site detail (4 sensors, units, 2 risk cards, 4 charts), accessibility audit |
| B Increasing landslide risk | 16/16 | Simulator → HIGH → linked candidate alert; observations SIMULATED; reviewer: notice, evidence, dialog focus, Escape cancels and removes dialog, acknowledge, badge refresh, single toast, action, empty reason blocked, resolve, UI = API status, ordered action log, audit chain verified in UI |
| C Flash flood | 6/6 | River scenario HIGH; re-apply → no duplicate alert; evidence is flood-specific |
| D Sensor outage | 14/14 | Reliability poor, 2 sensors offline and "not current", no LOW tier, data-gap alerts separate; gateway readings restore reliability; card labels observed reading; **observed/simulated drawn as separate lines; mixing disclosed; total blackout raises a data-gap alert** (4 checks added in the second pass) |
| E Unauthorised actions | 6/6 | Viewer UI has no controls; direct API acknowledge/action/config/simulator → 403; DB unchanged |
| UI | 26/26 | Every route renders; Not evaluated yet; incident search and synthetic filter; http(s)-only links; threshold editor errors; error states; template explanation fallback; no horizontal overflow at 390 px; mobile menu |
| F Restart & persistence | 6/6 | Server restarted on same DB: resolved alert, ordered actions, valid audit chain, telemetry resumes, current timestamps |
| G Production safeguards | 5/5 | `HDEWS_ENV=production`: demo routes 404, simulator hidden, no demo-password hint |

## 4. Coverage

Measured with `python scripts/coverage_report.py`, a **stdlib substitute for coverage.py** (which could not be installed). It uses Python 3.13 `sys.monitoring` for line events and bytecode conditional jumps for branches, and runs the full suite (pytest exit 0). Validation: on the same test subset, its line results for `risk_engine/engine.py` were **identical** to Python's independent `trace` module (136/149 lines, zero disagreement). Branch figures are bytecode-level and were not independently cross-checked. Four blocks marked `# pragma: no cover` are excluded and reported here rather than hidden: the PostgreSQL driver paths in `db.py` (2), the PostgreSQL advisory lock in `audit.py`, and the live LLM network call in `explanations.py`. None of them can execute in this environment.

| Critical area | Lines | Branches |
|---|---|---|
| Risk engine (pure logic: `engine`, `rules`, `config`, `features`, `playbook`) | **99.8 %** | **95.6 %** |
| Data freshness & features | 99.6 % | 93.5 % |
| Authentication & RBAC (`security.py`, `api/common.py`) | 99.4 % | 83.7 % |
| Sensor ingestion | 100.0 % | 97.7 % |
| Alert lifecycle (state transitions) | 98.3 % | 90.9 % |
| Audit chain | 100.0 % | 89.3 % |
| Simulator | 98.5 % | 89.6 % |
| Explanations (LLM guard) | 96.4 % | 83.3 % |
| API endpoints | 98.1 % | 76.8 % |
| ML evaluation harness | 95.2 % | 70.2 % |
| **Total** (2,695 lines, 1,410 branch outcomes) | **97.4 %** | **83.4 %** |

The ≥ 90 % line target for pure risk-engine logic and critical state-transition logic is met. Branch coverage of the risk engine is 95.6 %.

**Uncovered critical lines, reviewed one by one:**
* `services/alerts.py` 67–68: audit event for an alert whose severity changes. **Unreachable under the current rules** (hazard alerts open only at HIGH; data-gap alerts are always `DATA_GAP`). Kept for future tiers.
* `risk_engine/features.py` 271: `_fmt_age(None)` guard. It is only called once the age is known.
* `services/simulator.py` 101 (unknown preset; the API validates first), 124 (zero background rain for > 24 h; no preset uses it), 148 (unreachable `raise` for an unknown sensor type).
* Partial branches in the risk engine (`engine.py` 96/102, `rules.py` 110/115) are the "reliability note not added" or "value already finite" outcomes of defensive checks; both outcomes of every tier and reliability decision are exercised.
* The lower branch coverage in the API layer and ML harness is mostly optional query-parameter combinations and CLI flag paths.

Coverage was used as a diagnostic: an uncovered-line review found HDEWS-025 (a malformed stored password hash raised `binascii.Error`, turning login into a 500; re-confirmed on the baseline in the second pass). The raw per-file report, including missing and partial lines, is in `docs/coverage.json`.

## 5. Safety invariants: where they are tested

| # | Invariant | Tests |
|---|---|---|
| 1 | Tier and reliability separate | `test_inv1_*`; E2E A/D (separate chip parts) |
| 2–3 | Missing/stale critical data never LOW; benign rest → INSUFFICIENT_DATA | `test_inv2_inv3_*` (parametrised), randomised properties |
| 4 | Adverse evidence kept; underestimate disclosed | `test_inv4_*`, `test_lower_bound_only_claimed_when_missing_inputs_can_raise_tier` |
| 5 | Reliability reflects freshness/quality | `test_features.py` (usable freshness, delay, suspect, conflicts, mixed origins) |
| 6 | Points never presented as probabilities | `test_inv6_*` |
| 7 | Rule version and time on every assessment | `test_inv7_*` |
| 8 | Contributing factors traceable to evidence | `test_inv8_*`, property test (every contributing factor has evidence ids) |
| 9 | Threshold change applied consistently and audited | `test_inv9_*`, `test_api.py::test_site_config_validation_and_audit` |
| 10 | Deterministic | `test_inv10_*`, simulator determinism tests |
| 11 | Outage never lowers apparent risk | `test_inv11_*`, single-input property (1,000 cases), **multi-sensor outage property (1,000 cases, second pass)** |
| 12 | Data-gap alert distinct from hazard alert | `test_alerts_lifecycle.py`, `test_total_outage_including_rain_gauge_raises_data_gap_alert`, E2E D |

Property-based testing used seeded `random.Random` generators (4,000 cases in total), because Hypothesis could not be installed. Failures are reproducible from the seed in the test id.

## 6. Performance smoke (`docs/perf_results.json`)

Environment: 2 CPUs, SQLite file in WAL mode, in-process Starlette TestClient (no network). Dataset: 54,644 observations (30 days × 19 sensors), 20,016 audit events, 369 assessments. These are measurements, not targets.

| Endpoint | Median | Max | SQL statements |
|---|---|---|---|
| `GET /api/overview` | 17.6 ms | 22.1 ms | 37 |
| `GET /api/sites/{id}` | 5.3 ms | 6.1 ms | 12 |
| observations 24 h / 168 h | 4.7 / 18.2 ms | 5.9 / 28.6 ms | 4 |
| alerts list / assessments list / audit page | 3.0 / 2.8 / 3.2 ms | 3.2 / 2.9 / 3.6 ms | 3 |
| `GET /api/audit-log/verify` (20k events) | 190.8 ms | 236.5 ms | 3 |
| `POST /api/sites/{id}/assess` | 7.0 ms | 9.7 ms | 9 |
| `POST /api/demo/scenario` (1 site) | 40.3 ms | 86.3 ms | 783 |
| overview, 8 concurrent clients × 40 requests | 99.8 ms | 116.9 ms | — (0.51 s wall) |

Query plans for the unbounded tables use indexes (no full scans). Known limits: audit verification is linear in log size, and concurrent requests serialise on the single SQLite lock (median 18 → 100 ms at 8 concurrent).

## 7. Known limitations of this verification

* **PostgreSQL runtime** never executed (driver unavailable). Only the SQL migrations were verified with `psql`. HDEWS-021 (advisory lock) is unverified.
* **Live LLM provider** not called; only mocked providers (failures, injection, contradictions, length, caching) were tested.
* **Coverage tool** is a stdlib substitute for coverage.py. Line figures were cross-checked against the independent `trace` module (identical); branch figures are bytecode-level and have no independent cross-check here.
* **Property tests** use seeded `random`, not Hypothesis (no shrinking).
* **No dependency vulnerability scan**, **no Docker build**, **no frontend unit-test framework**, **no automated colour-contrast tool**.
* **E2E** runs Chromium only, on one machine.

## 8. Reproduce on your machine

```bash
pip install -r backend/requirements.txt          # + optionally: pip install "psycopg[binary]" pip-audit
cd backend && python -m pytest -rs && cd ..       # expect 468 passed, 1 skipped (0 skipped with psycopg + PostgreSQL)
./scripts/build_frontend.sh                       # needs tsc >= 5
python scripts/coverage_report.py                 # writes docs/coverage.json
python scripts/perf_smoke.py --days 30            # writes docs/perf_results.json
npm i -g playwright && npx playwright install chromium
python e2e/run_e2e.py --shots /tmp/hdews-shots    # expect 8/8 scenarios, 93/93 checks
python docs/evidence/second_pass_verify_claims.py .   # each line should show the fixed behaviour
```

---

## 9. Deployment-readiness pass (2026-10-29)

Same environment as above. Docker daemon available, but **Docker Hub, PyPI, npm, Render and Railway were blocked** by the
network policy, and no GitHub credentials were available. Everything below actually ran; anything that could not run is listed as unverified.

| Check | Command | Result |
|---|---|---|
| Backend suite (ML required) | `HDEWS_REQUIRE_ML=1 python -m pytest -rs` | **489 passed, 0 failed, 1 skipped** (PostgreSQL driver) in 134 s |
| Same suite, Windows-style text encoding | `LC_ALL=en_US.CP1252 PYTHONUTF8=0` (locale generated with `localedef`) | **489 passed, 1 skipped** |
| Same suite, pandas blocked as by Windows Smart App Control | stand-in `pandas` raising the exact OS error 4551 message | **471 passed, 2 skipped** (ML harness module, with reason; PostgreSQL). Before the fix: *Interrupted: 1 error during collection*, **0 tests run** |
| Lint | `ruff check --select E9,F,B …` and `--select PLW1514` (encoding) | All checks passed |
| Frontend build | `cd frontend && npm run build` (pinned `typescript` 7.0.2) | Output byte-identical to the committed `frontend/dist` |
| Browser E2E A–G | `PLAYWRIGHT_MODULE=… python e2e/run_e2e.py` (as in CI) | **8/8 scenarios, 93/93 checks** in 26.7 s |
| Container start-up path | `scripts/docker-entrypoint.sh python3 scripts/start.py` with a root-owned mode-700 data dir | Directory handed to `hdews`; **server process uid 10001**; seeded in `demo` mode; `/api/health` OK; **0** password occurrences in the log |
| CI Docker-job script | the step's exact script with a stand-in for the `docker` CLI | Exit 0: uid 10001; audit events 17 → 18 after restart (not reseeded); no password in logs |
| ML path | `python -m ml.evaluate … --record` on the **unit-test fixture** into a throwaway DB, then `GET /api/evaluation` | Recorded 2 uncalibrated runs and the page showed them. This proves the plumbing only, **not** model quality: no real labelled dataset exists |
| Coverage | `python scripts/coverage_report.py` | 97.0 % lines / 82.9 % branches overall; risk engine 99.8 % / 95.6 % |
| Workflow / Blueprint / Compose | YAML parse; `bash -n` on shell scripts | Parse OK |

**Not verified (environment limits):** `docker build` of the image; installing the pinned versions from public PyPI and npm
(including `typescript@7.0.2`); the GitHub Actions run, including the Windows job; the live Render deployment; Render's
`X-Forwarded-For` behaviour. The first CI run and the post-deploy checklist in `docs/DEPLOYMENT.md` close these gaps.
