# HDEWS bug audit report

**Audit date:** 2026-10-28 · **Baseline:** commit `5758680` (the prototype as delivered) · **Scope:** whole repository — backend, risk engine, database, ingestion, simulator, alert workflow, audit log, LLM explanations, ML harness, frontend source and build, scripts, docs.

## Independent second-pass verification

This audit was carried out in two passes. The first pass was interrupted before it produced test results. A second pass
then **treated the first pass's work as unverified**: it re-ran the baseline, reviewed every production-code change, and
re-checked the key claims with its own scripts. Results:

* **Baseline re-run (commit `5758680`, untouched):** 41 passed, 0 failed, 0 skipped; `tsc --strict` clean; `frontend/dist` byte-identical to a fresh compile of `frontend/src`.
* **Claims reproduced independently:** a new script written in the second pass (not the first pass's `docs/evidence/` scripts) reproduced HDEWS-001, 002, 003, 006, 008, 009, 010, 012, 013, 018, 020 and 023 on the baseline. It then confirmed each is fixed in the working tree. Output is in `docs/evidence/second_pass_verification.txt`.
* **Regression tests discriminate:** the first pass's new test files run against the baseline produced **158 failures** (per file: alerts 1, API contract 9, audit 7, auth 3, explanations 11, ingestion 11, ML 7, risk-engine boundaries 106, simulator 3) plus 2 modules that cannot import there. That matches the first pass's claim.
* **Code review:** no assertion was weakened. Two `pytest.raises(Exception)` checks were *tightened*. One first-pass test was found to **encode a defect** (see HDEWS-031 and correction R-2).
* **Evidence level for the remaining first-pass findings:** HDEWS-025 was also re-confirmed directly on the baseline module. HDEWS-005, 015, 016, 017, 019 and 026 rest on first-pass regression tests that are among the 158 baseline failures, so they discriminate, but they were not separately reproduced by a second-pass script. HDEWS-011 and 014 rest on the first pass's evidence file. HDEWS-024 is confirmed for the *fixed* code only (index plans in `perf_results.json`). The frontend fixes HDEWS-022 and 027–030 were reviewed line by line in the diff and are exercised by passing E2E checks; their "failed before the fix" statements come from the first pass and were not re-run.
* **New defects:** the second pass found six further defects (HDEWS-031 to 036), including two High-severity safety defects in the baseline that the first pass missed.

## How defects were confirmed

1. Every suspected defect was **reproduced against the unmodified baseline** before fixing: `docs/evidence/repro_baseline.txt` holds the output of the two reproduction scripts run on the baseline, next to the same scripts run on the fixed code.
2. Regression tests were written for each fix. The new test files were then **run against the baseline commit** in a separate git worktree. Of 420 tests, 158 failed and 2 modules could not be imported there.
3. Some baseline failures are **compatibility failures, not defect evidence**: tests that build `SensorHealth(usable_state=…)`, or import `SeedRefused` / `dedupe_readings`, cannot run on code that lacks those names. For those defects the evidence column cites the reproduction output instead. No defect below relies on a compatibility failure as its only evidence.

Severity: **Critical** = exploitable or safety-breaking in a documented configuration; **High** = wrong risk/safety output or data loss; **Medium** = incorrect behaviour with workaround or limited blast radius; **Low** = minor/hygiene.

## Summary

| ID | Sev. | Area | Defect | Status |
|---|---|---|---|---|
| HDEWS-012 | Critical | Seed / auth | Production seeding created admin accounts with the publicly documented password | Fixed, verified |
| HDEWS-003 | High | Risk features | Readings at the same timestamp from two sources were double-counted (rain 16.5 → 33.1 mm/h) | Fixed, verified |
| HDEWS-008 | High | Risk features | A sensor sending only unusable readings looked fresh; a 5 h old value was presented as current | Fixed, verified |
| HDEWS-009 | High | Risk engine | A sensor outage lowered the apparent risk (HIGH → LOW, ELEVATED → LOW) | Fixed, verified |
| HDEWS-001 | High | Ingestion / API | `Infinity` readings accepted; one such row made `/api/overview` return 500 for every user | Fixed, verified |
| HDEWS-013 | High | Scripts | `reset_db.py` deleted any SQLite file `DATABASE_URL` pointed to, and real observed data | Fixed, verified |
| HDEWS-002 | Medium | Ingestion | `unit` and unknown fields silently ignored (feet could be stored as metres) | Fixed, verified |
| HDEWS-004 | Medium | API | Request bodies of any size were buffered in memory | Fixed, verified |
| HDEWS-006 | Medium | Config | Threshold editor accepted booleans and misspelt keys; `1e999` returned 500 | Fixed, verified |
| HDEWS-007 | Medium | Ingestion (authz) | Any gateway key could write readings for every site | Fixed, verified |
| HDEWS-010 | Medium | Risk engine | Non-finite values compared as "normal" | Fixed, verified |
| HDEWS-015 | Medium | LLM | Provider errors outside a narrow set (e.g. malformed body) crashed the endpoint | Fixed, verified |
| HDEWS-016 | Medium | LLM | Explanations stating a different tier than the engine (or 4,000-char outputs) were accepted; no caching of provider calls | Fixed, verified |
| HDEWS-017 | Medium | ML harness | Crashed on missing/empty/malformed data; no leakage guard; positives without event IDs mis-counted | Fixed, verified |
| HDEWS-018 | Medium | Audit | Deleting the newest audit events (or deleting + re-linking) verified as valid | Fixed, verified |
| HDEWS-026 | Medium | Alerts | Actions recorded in the same second were listed in random order | Fixed, verified |
| HDEWS-021 | Medium | Audit (PostgreSQL) | Concurrent appends could fork the chain on PostgreSQL | Fix added, **unverified** (no driver) |
| HDEWS-005 | Low | Simulator | Misspelt scenario parameters silently ignored | Fixed, verified |
| HDEWS-011 | Low | Risk engine | "May understate the risk" claimed when the worst case equals the current tier | Fixed, verified |
| HDEWS-014 | Low | DB | In-memory SQLite connections never closed (16 ResourceWarnings in baseline run) | Fixed, verified |
| HDEWS-019 | Low | Auth | Username enumeration by login timing | Fixed, verified |
| HDEWS-020 | Low | API | Search text treated as SQL `LIKE` wildcards (`%` matched everything) | Fixed, verified |
| HDEWS-022 | Low | Frontend | Data-driven URLs rendered as links without a scheme check | Fixed, verified |
| HDEWS-023 | Low | API | Wrong HTTP method returned 404 "No such endpoint"; API paths fell through to the static mount | Fixed, verified |
| HDEWS-024 | Low | Performance | Two queries on unbounded tables were full scans | Fixed, verified |
| HDEWS-025 | Low | Auth | A malformed stored password hash made login raise (500) | Fixed, verified |
| HDEWS-027 | Low | Frontend | Sign-out could leave a revoked token in the browser | Fixed, verified |
| HDEWS-028 | Low | Frontend | Escape left closed dialogs (with duplicate form fields) in the page | Fixed, verified |
| HDEWS-029 | Low | Frontend | "Awaiting review" badge stayed stale after acknowledging in place | Fixed, verified |
| HDEWS-030 | Medium | Frontend | Sensor cards labelled real gateway readings "Simulated" (showed the registered feed, not the reading's origin) | Fixed, verified |
| HDEWS-033 | **High** | Risk features | Readings of different origins on one sensor were summed/differenced: observed − simulated "displacement" of 19.2 mm produced a **false HIGH** (could equally hide a real rise) | Fixed, verified (2nd pass) |
| HDEWS-036 | **High** | Alerting | A total outage at a site (rain gauge included) raised **no alert**: the data-gap rule demanded observed rain as proof of adverse weather | Fixed, verified (2nd pass) |
| HDEWS-031 | Medium | Migration | Upgrading an existing database gave existing gateways an empty scope, so **every reading was rejected** after the upgrade (introduced by the HDEWS-007 fix) | Fixed, verified (2nd pass) |
| HDEWS-032 | Medium | Ingestion | Idempotency keys were global: a second gateway reusing the same key scheme had readings **silently discarded** as "duplicates" | Fixed, verified (2nd pass) |
| HDEWS-034 | Medium | API / overview | Overview hourly-rain chart still double-counted duplicate readings (21.0 vs 16.9 mm); the HDEWS-003 fix covered only the engine | Fixed, verified (2nd pass) |
| HDEWS-035 | Low | Simulator | After downtime, caught-up simulated readings were stamped `received_at` in the past, claiming receipt while the server was down | Fixed, verified (2nd pass) |

**45 defects in total. The two audit passes found 36: 35 fixed and verified, and 1 fix unverifiable in this environment (HDEWS-021). The deployment-readiness pass added 9, all fixed. One of these (HDEWS-043) has an unverified image build.** By severity: 1 Critical, 7 High, 15 Medium, 13 Low. No threshold or point value was changed. Two documented behaviours changed deliberately and are recorded in the model card: effective criticality (HDEWS-009) and the data-gap alert criterion (HDEWS-036).


### Deployment-readiness audit (third pass, 2026-10-29)

| ID | Sev. | Area | Defect | Status |
|---|---|---|---|---|
| HDEWS-042 | **High** | Hosting / security | No safe internet-facing mode: `development` falls back to the **published** password `hdews-demo` if `HDEWS_DEMO_PASSWORD` is forgotten and prints the gateway key to platform logs; `production` cannot be used at all (demo seed refused, no way to create accounts) | Fixed, verified |
| HDEWS-037 | Medium | Tests / Windows | One blocked `import pandas` (Windows Smart App Control, OS error 4551) interrupted collection, so **0 of the backend tests ran**, although the server never imports pandas | Fixed, verified |
| HDEWS-038 | Medium | Windows portability | Text files read with the platform encoding: on cp1252 Windows the seed stored `16â€“17` for `16–17`, corrupting every non-ASCII character in incidents and sites | Fixed, verified |
| HDEWS-040 | Medium | Configuration | An unknown `HDEWS_ENV` (e.g. `prod`) silently behaved like `development`: simulator on, no secret checks | Fixed, verified |
| HDEWS-041 | Medium | Security / hosting | Behind a platform proxy every request has the proxy's address: one person's 10 failed logins locked **every** user out, and limits were not per client | Fixed, verified (platform header behaviour to confirm after deploy) |
| HDEWS-043 | Medium | Docker | Image hid seed failures (`2>/dev/null \|\| true`) and served an empty DB, ran as root, ignored `PORT`, installed the ML stack, had no `.dockerignore` | Fixed; start-up path verified locally, image build **unverified** (no registry access) |
| HDEWS-039 | Low | Scripts | `reset_db.py` built a SQLite URI by concatenation: a path containing `#` (or Windows backslashes) opened the wrong file, and a real HDEWS DB was refused | Fixed, verified |
| HDEWS-044 | Low | Tests | The test suite read the developer's local `.env`, so local settings could change test outcomes | Fixed, verified |
| HDEWS-045 | Low | Frontend build | No `package.json`: the compiler version was not pinned and the build used a bash script only | Fixed (`typescript` 7.0.2 pinned, `npm run build`); output identical to committed `dist` |

---

## Detailed findings

### HDEWS-012 — Production seeding created documented default credentials (Critical)
- **Where:** `backend/app/seed.py::seed`, `scripts/seed_demo_data.py`, `backend/app/main.py::create_app`
- **Impact:** with `HDEWS_ENV=production` and no `HDEWS_DEMO_PASSWORD`, the seed created `admin/analyst/reviewer/viewer` with password `hdews-demo`, which is printed in the README. Anyone could take full admin control of a production instance.
- **Reproduce (baseline):** `HDEWS_ENV=production DATABASE_URL=sqlite:///p.db python scripts/seed_demo_data.py` → exit 0, "password: hdews-demo".
- **Expected:** the demo dataset is refused in production; production never runs with documented passwords. **Actual:** seeded.
- **Root cause:** the seed had no environment check, and the app had no startup credential check.
- **Fix:** `seed()` raises `SeedRefused` in production. `create_app()` refuses to start in production if any active account verifies against a documented default password.
- **Tests:** `test_db.py::test_seed_refused_in_production`, `::test_production_refuses_to_start_with_default_passwords`.
- **Verification:** repro on fixed code exits 1; tests pass. The baseline test module could not be imported (it needs `SeedRefused`), so the reproduction above is the evidence.

### HDEWS-003 — Same-timestamp readings from different origins were double-counted (High, safety)
- **Where:** `risk_engine/features.py::rain_accumulation` (and all indicators). Also `routes_core.overview` hourly rain.
- **Impact:** when a real gateway and the simulator (or two sources) reported the same interval, rainfall was summed twice. That inflated the tier, could produce false HIGH alerts, and corrupted the evidence.
- **Reproduce (baseline):** re-send SNP-05's last-hour simulated rain readings as OBSERVED → `rain_1h_mm` 16.5 → **33.1**.
- **Root cause:** the unique key is (sensor, time, origin), so both rows are legitimately stored, but the features summed every row.
- **Fix:** `dedupe_readings()` keeps one reading per timestamp, choosing by origin precedence (OBSERVED > IMPORTED > DERIVED > SIMULATED) before usability. A simulated value can therefore never stand in for a real one. Conflicting values are counted and degrade reliability with a note.
- **Tests:** `test_features.py::test_duplicate_timestamps_from_two_origins_are_not_double_counted`, `::test_conflicting_duplicates_are_flagged_and_degrade_reliability`, `::test_simulated_reading_never_replaces_an_observed_one_even_if_unusable`; `test_ingestion.py::test_observed_rain_does_not_double_count_with_simulated` (**fails on baseline**).
- **Verification:** repro on fixed code 16.5 → 16.5; tests pass.

### HDEWS-008 — Unusable recent readings made an old value look current (High, safety)
- **Where:** `risk_engine/features.py::sensor_health`, `latest_value`, `change_over`
- **Impact:** a sensor reporting only `bad`-quality readings was classed FRESH (freshness came from the newest *message*). Its last good value, 5 h old, was then shown and scored as "available", violating "a stale sensor must be visibly stale".
- **Reproduce (baseline):** 5 h-old good soil readings followed by 4 h of `bad` readings → `status=available`, `as_of` 5 h old, state FRESH.
- **Fix:** `SensorHealth.usable_state` is derived from the newest *usable* reading, and indicators use it. A reporting-but-unusable sensor adds a reliability note.
- **Tests:** `test_features.py::test_reporting_sensor_with_only_unusable_recent_readings_is_not_current`, `::test_reporting_sensor_whose_usable_data_is_hours_old_is_missing_with_clear_note`.
- **Verification:** fixed code reports `status=stale`, reliability POOR, tier not LOW. The test module needs the new API (`dedupe_readings`), so the reproduction is the baseline evidence.

### HDEWS-009 — A sensor outage lowered apparent risk (High, safety invariant 11)
- **Where:** `risk_engine/engine.py::assess`
- **Impact:** HIGH driven by slope displacement became **LOW** when the extensometer went offline: displacement was a non-critical input, so its loss only degraded reliability. A seeded randomised property test later found the general case: losing *any* configured non-critical input that carried points (e.g. a gap in the 1-hour river rise) could turn ELEVATED into LOW.
- **Reproduce (baseline):** displacement 7 mm/24 h → HIGH/GOOD. Extensometer offline 7 h → **LOW/DEGRADED**.
- **Root cause:** criticality was a static per-input flag, so missing non-critical inputs simply dropped their points.
- **Fix:** effective criticality. An unavailable input whose sensor is configured at the site is treated as critical if its data could change the tier. LOW is then never asserted while configured evidence that could contradict it is missing. Inputs with no sensor configured at the site keep the documented behaviour (DEGRADED, not an outage). Documented in the model card and `/api/rules`. No thresholds changed.
- **Tests:** `test_risk_engine_boundaries.py::test_inv11_outage_of_decisive_sensor_cannot_lower_apparent_risk`, `::test_inv11_unconfigured_sensor_is_not_treated_as_outage`, `::test_property_making_an_input_unavailable_never_lowers_the_tier` (1,000 randomised cases).
- **Verification:** fixed code → INSUFFICIENT_DATA/POOR. The property test failed 9/10 seeds against the first, narrower fix, which is why the fix was generalised.
- **Behaviour change:** UKM-06 (extensometer in maintenance) now reports landslide `INSUFFICIENT_DATA` rather than `LOW`. Under the invariant this is intended.

### HDEWS-001 — Infinity readings accepted and crashed the dashboard (High)
- **Where:** `api/common.py::body_as/ok`, `services/ingestion.py::Reading`
- **Impact:** `{"value": Infinity}` (accepted by Python's JSON parser) was stored with quality `bad`. Every endpoint returning that row (the overview, the site observations) then failed with 500 because Infinity is not valid JSON output. A single malformed gateway message took the dashboard down for all users.
- **Reproduce (baseline):** POST the reading → 202; `GET /api/overview` → **500**; `GET /api/sites/AGM-03/observations` → **500**.
- **Fix:** non-finite JSON constants are rejected at parse time (400), `1e999` is rejected by Pydantic (`allow_inf_nan=False`, 422), and responses sanitise any legacy non-finite values to `null`.
- **Tests:** `test_ingestion.py::test_nan_and_infinity_literals_rejected` (3 cases), `::test_overflowing_number_rejected`, `::test_previously_stored_infinity_cannot_crash_views`. All **fail on baseline**.

### HDEWS-013 — `reset_db.py` destroyed unrelated data (High)
- **Where:** `scripts/reset_db.py`
- **Impact:** it unlinked whatever SQLite file `DATABASE_URL` named, including non-HDEWS files and HDEWS databases holding real OBSERVED readings.
- **Reproduce (baseline):** create `user.db` with table `precious`, point `DATABASE_URL` at it, run the script → table gone. Captured in the evidence file.
- **Fix:** refuses non-HDEWS files (required tables absent), refuses to discard non-simulated observations without `--force`, refuses production and non-SQLite. It opens the file read-only to inspect it.
- **Tests:** `test_db.py::test_reset_refuses_non_hdews_database`, `::test_reset_refuses_to_discard_observed_data_without_force`, `::test_reset_refused_in_production`.

### HDEWS-002 — Ingestion ignored units and unknown fields (Medium)
- **Where:** `services/ingestion.py::Reading`. **Impact:** `{"value": 9.8, "unit": "ft"}` was stored as 9.8 m, and typos in field names were dropped silently.
- **Fix:** `extra="forbid"`; an optional `unit` must match the sensor registry or the reading is rejected with a reason.
- **Tests:** `test_ingestion.py::test_unit_must_match_sensor_registry`, `::test_unknown_fields_rejected` (**fail on baseline**).

### HDEWS-004 — Unbounded request bodies (Medium)
- **Where:** `api/common.py::body_as`. **Impact:** memory exhaustion. A 3.9 MB ingestion body was fully parsed before its 500-reading limit was checked.
- **Fix:** `read_body()` enforces a 1 MB limit using both `Content-Length` and streamed size → 413.
- **Tests:** `test_api_contract.py::test_body_size_limit`, `test_ingestion.py::test_batch_limits` (**fail on baseline**).

### HDEWS-006 — Threshold editor accepted invalid configuration (Medium)
- **Where:** `risk_engine/config.py::validate_site_overrides`.
- **Impact:** `true` was accepted as a threshold (Python `bool` ⊂ `int`). A misspelt key such as `rain_24hr_mm` was accepted but had no effect, so an admin believed a threshold had changed. Non-finite values led to 500.
- **Fix:** values must be finite non-bool numbers; only known keys and `watch`/`high` sub-keys are allowed; errors list the allowed keys.
- **Tests:** `test_api_contract.py::test_threshold_editor_rejects_invalid_config_and_leaves_it_unchanged` (7 cases, 3 **fail on baseline**), `::test_threshold_editor_rejects_infinity` (**fails on baseline**), `test_risk_engine_boundaries.py::test_threshold_validation_messages`.

### HDEWS-007 — Gateway keys were not scoped to sites (Medium, authorization)
- **Where:** `services/ingestion.py::ingest`. **Impact:** a horizontal-privilege problem: one gateway key could write readings for every site (documented then as a known limitation).
- **Fix:** migration `002_ingest_scope` adds `data_sources.ingest_site_scope` (JSON list; NULL = nothing). Readings for sensors outside the scope are rejected. The demo gateway is scoped to the six pilot sites.
- **Tests:** `test_ingestion.py::test_source_site_scope_is_enforced` (**fails on baseline**), `test_db.py::test_upgrade_from_001_preserves_existing_data`.

### HDEWS-010 — Non-finite values scored as "normal" (Medium)
- **Where:** `risk_engine/rules.py::evaluate_factor`, `features.py`. **Impact:** `NaN >= threshold` is False, so a NaN reading produced level "normal", status "available" and tier LOW/GOOD (defence in depth; ingestion now blocks these).
- **Fix:** non-finite values are unusable everywhere. **Tests:** `test_risk_engine_boundaries.py::test_non_finite_indicator_values_are_never_scored_normal`, `test_features.py::test_non_finite_readings_are_excluded`. **Baseline evidence:** reproduction B10.

### HDEWS-015 — LLM provider failures could crash the endpoint (Medium)
- **Where:** `services/explanations.py::explain`. **Impact:** only five exception types were caught. A malformed provider body (`AttributeError`), or a provider returning non-text, produced a 500.
- **Fix:** any provider exception falls back to the template, and only the exception *type* is reported (never the message, which may contain request details).
- **Tests:** `test_explanations.py::test_any_provider_failure_falls_back` (8 cases, 2 **fail on baseline**), `::test_endpoint_survives_provider_outage`.

### HDEWS-016 — Unsafe LLM explanations accepted; unbounded provider calls (Medium)
- **Impact:** "The risk tier is LOW and conditions are safe" passed the numeric-only grounding check for an ELEVATED assessment. 4,000-character outputs were accepted. Every page view called the provider.
- **Fix:** reject outputs that attach a different tier to the overall risk, outputs over 1,200 characters, and empty outputs. Explanations are cached per (immutable) assessment.
- **Tests:** `test_explanations.py::test_unsafe_or_unusable_llm_output_is_rejected` (9 cases, 7 **fail on baseline**), `::test_prompt_injection_in_site_name_cannot_change_the_stated_tier` (**fails on baseline**), `::test_endpoint_caches_explanations_to_bound_provider_calls` (**fails on baseline**).

### HDEWS-017 — ML harness robustness and leakage guard (Medium)
- **Where:** `ml/evaluate.py::load`. **Impact:** missing or empty files gave tracebacks; non-numeric or infinite features crashed sklearn. Windows ending *after* the event onset (leakage) were accepted. Positive rows without `event_id` were dropped from event counts.
- **Fix:** each case raises `DatasetError` with a clear message (exit code 2).
- **Tests:** `test_ml_harness.py::test_invalid_datasets_rejected` (9 cases, 6 **fail on baseline**), `::test_missing_and_empty_files_rejected` (**fails on baseline**).

### HDEWS-018 — Audit verification missed truncation (Medium)
- **Where:** `services/audit.py::verify_chain`. **Impact:** a hash chain cannot detect removal of its newest events. Deleting the last event verified as `valid: true`.
- **Fix (SQLite):** verify contiguous `seq` values against the `AUTOINCREMENT` high-water mark in `sqlite_sequence`. This also catches a deletion where the attacker recomputed every later hash. `head_hash` is returned so it can be anchored outside the database.
- **Tests:** `test_audit_chain.py::test_truncated_tail_detected`, `::test_entire_log_deleted_detected`, `::test_deletion_with_rewritten_hashes_detected_by_sequence_gap` (**all fail on baseline**).
- **Residual:** an attacker with full write access who also rewrites `sqlite_sequence` and every hash is detectable only against an externally anchored `head_hash`. See SECURITY_AUDIT.md.

### HDEWS-026 — Alert actions displayed out of order (Medium)
- **Where:** `routes_alerts.get_alert` ordered by `created_at` (one-second resolution), then a random id. **Impact:** the reviewer timeline could show "field verification" before "acknowledge". Found by an intermittent failure in the new restart test.
- **Fix:** migration `004_action_sequence` adds a per-alert `seq` (backfilled from insertion order), used for ordering.
- **Tests:** `test_alerts_lifecycle.py::test_actions_within_the_same_second_keep_recorded_order` (**fails on baseline**), `test_db.py::test_restart_persistence_of_alert_workflow`.

### HDEWS-021 — PostgreSQL audit appends not serialised (Medium, potential)
- **Where:** `services/audit.py::record`. **Issue:** under PostgreSQL's default isolation, two transactions can read the same last hash and append siblings, forking the chain. (SQLite serialises writes, so it is unaffected.)
- **Fix:** `pg_advisory_xact_lock` before reading the chain head. **Unverified:** `psycopg` is not installable here, so the PostgreSQL runtime path has never executed. Listed under unresolved verification.

### HDEWS-005 — Misspelt scenario parameters ignored (Low)
`ScenarioParams` now forbids extra fields and non-finite values. Tests: `test_api_contract.py::test_scenario_validation` (**fails on baseline**), `test_simulator.py::test_invalid_custom_inputs_rejected` (**fails on baseline**). Duplicate `site_ids` are now de-duplicated (`test_duplicate_site_ids_are_applied_once`, **fails on baseline**).

### HDEWS-011 — Inconsistent "may understate" claim (Low)
For score 2 (ELEVATED) with one incomplete input worth at most +1, the baseline set `tier_is_lower_bound=true` and the summary said "may understate the risk", while `max_possible_tier` was also ELEVATED. That is verified on the baseline engine in `docs/evidence/repro_baseline.txt`. **Fix:** the flag is true only when `max_possible_tier` exceeds the tier. **Test:** `test_lower_bound_only_claimed_when_missing_inputs_can_raise_tier`.

### HDEWS-014 — Unclosed database connections (Low)
The baseline test run emitted 16 `ResourceWarning: unclosed database`. `Database.close()` was added. The app closes only databases it opened, and fixtures close theirs. The final runs show no such warnings.

### HDEWS-019 — Username enumeration by timing (Low)
Unknown usernames skipped scrypt (~50 ms faster). A dummy verification now runs. Test: `test_auth_rbac.py::test_unknown_username_still_runs_password_hashing` (**fails on baseline**).

### HDEWS-020 — LIKE wildcards in search (Low)
`%` and `_` in incident search or the audit `event_prefix` matched everything. Input is now escaped (`ESCAPE '\'`). Test: `test_api_contract.py::test_search_wildcards_are_literal` (**fails on baseline**).

### HDEWS-022 — Unchecked link schemes (Low)
Incident and data-source URLs went straight into `href`. A `javascript:` URL in imported data would have been clickable; CSP limits but does not remove the risk. `safeUrl()` renders only http(s). Verified by the E2E check "external links are http(s) only" and the source scan in `test_security.py`.

### HDEWS-023 — Wrong methods returned 404; API fell through to static files (Low)
Root cause: the static `Mount("/")` fully matched every path, so method mismatches on API routes reached the file server, and the 405 handler was wired to the 404 function. The API is now its own `Mount("/api")` with a real 405 + `Allow` header. Test: `test_api_contract.py::test_wrong_method_is_405_with_allow_header` (**fails on baseline**).

### HDEWS-024 — Full scans on unbounded tables (Low, performance)
`EXPLAIN QUERY PLAN` showed `SCAN audit_log` for the overview's tier changes and `SCAN assessments + TEMP B-TREE` for the unfiltered assessment list. Migration `003_query_indexes` turns both into index searches (`docs/perf_results.json`).

### HDEWS-025 — Malformed stored hash made login 500 (Low)
`verify_password` decoded base64 outside its `try`. Found by a coverage-gap test. Tests: `test_auth_rbac.py::test_malformed_stored_password_hash_never_verifies`, `::test_login_with_corrupted_stored_hash_is_401_not_500` (**both fail on baseline**).

### HDEWS-027 — Sign-out could leave a revoked token (Low)
The local session was cleared only after awaiting the server logout. Navigating during that request left a revoked token, and the next load bounced between screens with 401s. Found by E2E Scenario B. Now the session is cleared first, then revoked server-side with a `keepalive` request.

### HDEWS-028 — Escape left dialogs in the page (Low)
A native `<dialog>` closed by Escape was never removed, so later dialogs duplicated form fields. Found by E2E Scenario B. Dialogs now remove themselves on `close`. E2E check: "Escape removes the dialog from the page".

### HDEWS-029 — Stale "awaiting review" badge (Low)
The badge refreshed only on navigation or a 45 s timer. Any successful mutating API call now emits `hdews:mutated` and the shell refreshes the badge. E2E check: "sidebar badge updates after acknowledging" — failed before the fix, passes after.

### HDEWS-030 — Sensor cards mislabelled observed readings as simulated (Medium)
- **Where:** `frontend/src/ui.ts::sensorCard`. **Impact:** after real gateway readings arrived for a sensor registered to the simulator, the card showed the observed value tagged "Simulated telemetry gateway — Simulated". In an evidence-first tool, mislabelling the provenance of the value on screen is a misleading UI state.
- **Found by:** reviewing the E2E Scenario D screenshot after recovery.
- **Fix:** the card shows the origin of the displayed reading ("This reading: Observed") separately from the registered feed.
- **Test:** E2E check "card labels the latest (gateway) reading as Observed, not Simulated".

### HDEWS-033 — Readings of different origins were combined (High, safety)
- **Where:** `risk_engine/features.py::build_features` (all indicators); frontend `charts.ts::lineChart`.
- **Impact:** the HDEWS-003 fix collapsed only readings at the *same* timestamp. A real gateway reports at its own times
  (e.g. 10:07) while the simulator writes 10:00/10:15, so both series were still combined. The 24 h displacement became
  (real extensometer value − simulated value 24 h earlier), which is meaningless and gave a **false HIGH**. With the
  opposite sign, it would hide a real rise. Rainfall was summed across both series, and the chart drew one line joining them.
- **Reproduce (current tree before fix, and baseline):** normal scenario on SNP-05, push one observed extensometer reading of 31.2 mm three minutes off-grid → `displacement_24h_mm` = **19.21 mm**, level high. Rain: simulated 17.4 mm + one observed 9 mm → 26.4 mm.
- **Root cause:** freshness and calculations treated all origins of a sensor as one series.
- **Fix:** `single_origin()` keeps only the highest-precedence origin present for each sensor (observed > imported >
  derived > simulated, the same rule as HDEWS-003). Ignored readings are disclosed in a reliability note (at most
  DEGRADED). The chart draws one line per origin. **Behaviour note:** after a test reading is pushed to a simulated
  sensor, that sensor follows the observed feed until the reading leaves the 26 h window. If no further observed
  readings arrive, it correctly goes stale.
- **Tests:** `test_regressions_round2.py::test_change_indicators_never_mix_observed_and_simulated_series`, `::test_rain_accumulation_does_not_add_observed_readings_to_simulated_ones` (both failed before the fix); E2E D "chart draws observed and simulated readings as separate lines", "mixed-origin readings disclosed".

### HDEWS-036 — A total outage raised no alert (High, safety)
- **Where:** `services/alerts.py::process_assessment`.
- **Impact:** with every sensor at SNP-05 offline during a storm, both hazards were correctly `INSUFFICIENT_DATA/POOR`,
  but **no alert reached the review queue**. A partial outage did raise one. A blackout is often caused by the storm
  itself (power or comms), which makes it the case that most needs a reviewer.
- **Root cause:** a data-gap alert required "adverse" conditions, defined as observed 1 h rain ≥ 10 mm or evidence ≥ ELEVATED. When the
  rain gauge is down, observed rain cannot exist, so the condition could never be met.
- **Fix:** a data-gap alert is also raised when the site's *configured* rain gauge is missing or stale ("adverse weather
  cannot be ruled out"). Sites without a rain gauge are excluded so a design limit cannot re-alert forever. Severity stays
  `DATA_GAP` and kind `DATA_QUALITY`, never a hazard alert.
- **Tests:** `::test_total_outage_including_rain_gauge_raises_data_gap_alert` (failed before the fix), `::test_no_data_gap_alert_when_rain_gauge_shows_fair_weather` (guards against alert spam); E2E D "total blackout raises a data-gap alert in the UI".

### HDEWS-031 — Upgrade silently disabled existing gateways (Medium, availability)
- **Where:** migration `002_ingest_scope` (both dialects), introduced by the first-pass fix for HDEWS-007.
- **Impact:** an existing push source got `ingest_site_scope = NULL` ("no sites"), so every reading was rejected with HTTP 200. Nothing in the app could set the scope. In an early-warning system this is a silent feed outage after an upgrade.
- **Fix:** the migration backfills existing push sources with every existing site (their pre-upgrade access). New tool `scripts/set_ingest_scope.py` narrows the scope and is audited. Verified on SQLite and on PostgreSQL 16 with data.
- **Tests:** `::test_upgrade_keeps_existing_gateway_able_to_write`, `::test_set_ingest_scope_script`; `test_db.py::test_upgrade_from_001_preserves_existing_data` corrected (see R-2).

### HDEWS-032 — Idempotency keys collided across sources (Medium, data loss)
- **Where:** `services/ingestion.py::ingest`. **Impact:** gateway B's message `msg-1` was dropped as a duplicate of gateway A's `msg-1`.
- **Fix:** keys are stored namespaced as `<source_id>:<key>`. Migration `005_idempotency_per_source` converts existing keys; it is idempotent and verified on PostgreSQL 16. Retries from the same source are still deduplicated.
- **Test:** `::test_idempotency_keys_are_scoped_per_source` (failed before the fix).

### HDEWS-034 — Overview rain chart double-counted (Medium)
- **Where:** `api/routes_core.py::overview`. **Fix:** the chart reuses the engine's `dedupe_readings` and `single_origin`, so the dashboard and the assessment can no longer disagree. It reports which origin each gauge shows (`rain_hourly.origin`, shown in the UI).
- **Test:** `::test_overview_rain_chart_does_not_double_count` (failed before the fix: newest hour 21.0 instead of 16.9 mm).

### HDEWS-035 — Back-dated receipt times after downtime (Low, provenance)
- **Where:** `services/simulator.py::tick`. **Impact:** after a 3 h outage, catch-up readings claimed `received_at` during the outage. **Fix:** caught-up readings record the true receipt time; observation times are unchanged. The scenario history written by `apply_scenario` remains a deliberately synthetic past.
- **Test:** `::test_catch_up_after_downtime_records_true_receipt_time` (failed before the fix).


### HDEWS-037: blocked ML import aborted the whole test suite (Medium)
- **Cause on the user's machine:** Windows error 4551, "An Application Control policy has blocked this file". This means
  **Smart App Control** or **App Control for Business (WDAC)** refused to load pandas' compiled extension `nattype`, which is
  not Authenticode-signed. It is a security-policy decision, not an incompatible or broken dependency. It could not be
  reproduced on Windows here; the user can confirm it in *Windows Security → App & browser control* or in the
  CodeIntegrity/Operational event log. Disabling the protection is **not** recommended.
- **Project defect:** `tests/test_ml_harness.py` imported pandas at module level, so pytest reported
  "Interrupted: 1 error during collection" and ran **none** of the 468 tests. Reproduced here with a stand-in `pandas` that
  raises the same ImportError.
- **Fix:** the module skips itself with the reason shown, and `HDEWS_REQUIRE_ML=1` (set in CI) turns the skip back into an
  error. Requirements are split: `requirements.txt` (server), `-dev` (tests), `-ml` (harness). The Docker image installs the
  server requirements only.
- **Tests:** `test_portability.py::test_blocked_ml_stack_skips_only_the_ml_harness`, `::test_ci_mode_turns_a_broken_ml_stack_into_an_error`,
  `::test_backend_runtime_never_imports_the_ml_stack`. Full suite with pandas blocked: 453 passed, 2 skipped (before the fix: interrupted, 0 run).

### HDEWS-038: platform-encoding text reads (Medium)
- **Reproduced** with a generated `en_US.CP1252` locale and `PYTHONUTF8=0` (the Windows default): the seeded note
  `16–17 June` was stored as `16\xe2\u20ac\u201c17`. Seven reads/writes in `app/`, `scripts/` and `e2e/` lacked an encoding.
- **Fix:** explicit UTF-8 everywhere (tests too).
- **Tests:** `test_portability.py::test_all_text_file_io_specifies_an_encoding` (AST scan), `::test_seeded_text_is_identical_without_utf8_mode`. Both failed under CP1252 with the old seed, and the whole suite was also run under CP1252.

### HDEWS-039: SQLite URI built by concatenation (Low)
`reset_db.py` used `f"file:{path}?mode=ro"`. It now uses `path.resolve().as_uri()`, which percent-encodes and handles `C:\`.
Test: `test_portability.py::test_reset_db_handles_special_characters_in_path`, which fails with only the old line restored.

### HDEWS-040: unknown HDEWS_ENV accepted (Medium)
`Settings` now validates `HDEWS_ENV` ∈ {development, test, demo, production} and `CLIENT_IP_SOURCE`; start-up fails with
the allowed values. Test: `test_deployment.py::test_unknown_environment_name_is_rejected`.

### HDEWS-041: rate limits keyed on the proxy address (Medium)
`CLIENT_IP_SOURCE` = `peer` (default) | `x-forwarded-for-first` | `x-forwarded-for-last`. Render staff state that Render
sets the *first* `X-Forwarded-For` entry to the real client and only appends to the header; this is not in the formal docs,
so the README includes a post-deploy check. Tests: `test_deployment.py::test_behind_proxy_one_user_cannot_exhaust_everyones_login_limit`,
`::test_client_ip_source_last_uses_the_hop_added_by_our_proxy`, `::test_invalid_client_ip_source_rejected`.

### HDEWS-042: no safe hosted mode (High)
- **Fix:** `HDEWS_ENV=demo`, the hosted demonstration, keeps the simulator. Its seed requires `HDEWS_DEMO_PASSWORD` of at least 12 characters and
  not a documented default, refuses placeholder ingest keys, and prints no secrets. Start-up refuses default passwords in
  `demo` and `production`, and the login hint does not mention the default. `scripts/manage_users.py` creates accounts, sets
  passwords (revoking sessions) and disables or enables accounts. It is audited, works in production, and never takes passwords on the
  command line.
- **Tests:** `test_deployment.py` (password/key refusals, no secrets printed, simulator and guard in demo, production bootstrap
  and rotation with session revocation).

### HDEWS-043: container image (Medium)
New `Dockerfile` (runtime deps only, non-root via `scripts/docker-entrypoint.sh` + `setpriv`, `PORT`, `HEALTHCHECK`),
`.dockerignore`, and `scripts/start.py` as the single start path, which fails loudly. **Verified locally without Docker:** the
entrypoint, given a root-owned mode-700 data directory, chowned it and ran the server as uid 10001. The complete CI Docker-job
script passed with a stand-in `docker` CLI (non-root, data kept across restart, no password in logs). **Not verified:** `docker
build` (Docker Hub blocked) and installing the pinned packages from public PyPI (blocked).

### HDEWS-044 / 045
`HDEWS_DOTENV=0` disables `.env` loading; `conftest.py` sets it. `frontend/package.json` pins `typescript` 7.0.2 with
cross-platform `npm run build`, and its output is byte-identical to the committed `dist`.

---

## Defects in the work itself (found and fixed during this audit)

These were caught by the new tests, are recorded for transparency, and never shipped:
- **Regression R-1:** the first HDEWS-014 fix closed databases passed in by callers at app shutdown. For an in-memory DB that silently erased it. Caught by `test_ingestion.py::test_database_failure_mid_batch_rolls_back_everything`; fixed (`owns_database`).
- **Test defect T-1:** `test_recovery_only_after_valid_observations_arrive` depended on where wall-clock time fell in the 15-min grid: a 40-min-delayed sensor was 41–51 min old, straddling the 45-min stale boundary. Fixed by pinning the clock, and the expectation was corrected to the (correct) HDEWS-009 behaviour.
- **Test defect T-2:** a fake broken migration named `003_*` sorted before the real `003_query_indexes`. Renamed `999_broken`.
- **E2E harness defects:** a selector matched helper text as well as the button; Chromium's console echo of *intentionally* tested 403/404/422 responses was counted as an error (responses are still checked individually); the badge was read before its first load.
- **Correction R-2 (second pass):** the first pass's `test_upgrade_from_001_preserves_existing_data` asserted `ingest_site_scope is None` for an upgraded gateway, which *encoded* defect HDEWS-031. It now asserts the backfilled scope.
- **Second-pass test hygiene:** `ruff` flagged two unused imports in the new `test_regressions_round2.py` (fixed). Two tests that read the stored `idempotency_key` column directly were updated for the namespaced format; their assertions are unchanged.
- **Lint:** five tests used `pytest.raises(Exception)`, which would pass on unrelated errors. They are now tightened to `sqlite3.IntegrityError`/`ValidationError` with message matches.

## Dead code, duplication and architectural risks (not defects)

| Item | Finding | Action |
|---|---|---|
| `features.SENSOR_METRICS`, `alerts.OPEN_STATUSES` | Defined, never used | Removed |
| `alerts._upsert` severity-change branch | Unreachable under current rules (hazard alerts are always HIGH, data-gap always DATA_GAP) | Kept for future tiers; documented |
| `security.PERMISSIONS["manage_sources"]` | No endpoint uses it | Kept (part of `/api/auth/me` output); documented |
| `MLModelInterface.get` | Interface only; no engine path calls it | Intentional (no validated model exists) |
| Single DB lock + synchronous DB calls inside async handlers | Requests serialise; 8 concurrent overview requests: median 133 ms vs 16 ms sequential (`perf_results.json`) | Acceptable for one node; move to a thread pool / async driver before scale-out |
| Background loop per process | `uvicorn --workers N` would run N loops (duplicates are prevented by constraints, but the work repeats) | Documented: run one worker or a separate scheduler |
| In-memory rate limiter | Per process; resets on restart | Documented |
| Overview queries | 37 SQL statements (per-sensor freshness, per-site/hazard latest) | Bounded by sensor count; acceptable at prototype scale |
| PostgreSQL `latest_assessment` | No tie-break for same-second assessments (SQLite uses `rowid`) | Unverified path; listed |
| Frontend charts | Window end uses the client clock (`Date.now()`) | A skewed client clock shifts the chart window; low impact |
| Pydantic lax mode | Numeric strings such as `"12.5"` are accepted as numbers in ingestion | Documented in a test; left as is |
| Audit verification cost | Re-hashes the whole chain in memory: 191 ms at 20,016 events (`perf_results.json`), linear growth | Add checkpointed verification before long-term operation |
| Data retention | Assessments (~2,600/day with the background loop, several kB each), observations and sessions are never pruned | Add retention/archival before long-term operation |
| Rate-limiter memory | Per-IP buckets are never evicted | Bounded by distinct client IPs; evict idle keys before exposure to the internet |
| Production bootstrap | Seeding is refused in production and no user-management endpoint exists, so a production instance has no way to create accounts | Intentional fail-safe for the prototype; an identity provider or admin CLI is required before real use |

## Unresolved items and external verification required
0a. **Residual (ML evaluation claims):** the harness refuses data whose `label_source` says "synthetic", but it cannot tell whether a dataset is real. Recording fixture data with `--record` makes the evaluation page show "EVALUATED". This was shown in a throwaway DB in the third pass. Only record runs on expert-labelled real data, and never record into the hosted database from tests.
0. **Recommendation, not implemented:** per-account login lockout, and recording of failed logins in the audit log.
1. **PostgreSQL runtime path** (incl. HDEWS-021, `latest_assessment` tie-break): needs `pip install "psycopg[binary]"` and the suite run against PostgreSQL. All four migrations were verified to apply on PostgreSQL 16 with `psql`.
2. **Live LLM provider:** only exercised with mocks; a real key and provider are needed.
3. **Real data sources, calibrated thresholds, model validation, field validation:** out of scope for software testing; see `docs/evaluation-plan.md`.
4. **Dependency vulnerability scan:** `pip-audit` / `npm audit` need network access; not run.
5. **Docker image:** written, never built (no Docker daemon).
