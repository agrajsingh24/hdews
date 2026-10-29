# HDEWS — Himalayan Disaster Early Warning System (prototype)

**From environmental signals to explainable, human-reviewed early action.**

HDEWS is a working decision-support prototype for rainfall-triggered landslide and flash-flood risk in a pilot study area in **Rudraprayag district, Uttarakhand**. It ingests sensor observations, computes transparent hazard assessments that keep *risk* and *data reliability* separate, raises candidate alerts for authorised human review, and records every decision in a tamper-evident audit log.

> **Safety boundary.** HDEWS is a research prototype. It is **not** a certified or official warning service. All sensor telemetry in the demo is **SIMULATED**; thresholds are **uncalibrated demonstration settings**; candidate alerts are internal review items and **nothing is ever sent to the public**. Follow the responsible authority's approved SOPs. See [docs/safety-and-limitations.md](docs/safety-and-limitations.md).

---

## 1. Quick start

Prerequisites: **Python 3.11+** (tested on 3.13). Node 22 is only needed to rebuild the frontend; a compiled build is committed in `frontend/dist`.

**Linux / macOS**
```bash
cd hdews
python -m pip install -r backend/requirements-dev.txt   # server + test tools
python -m pip install -r backend/requirements-ml.txt    # optional: offline ML evaluation harness
cp .env.example .env                                     # then set HDEWS_DEMO_PASSWORD
./scripts/run_dev.sh                                     # migrates, seeds an empty DB, serves http://127.0.0.1:8000
```

**Windows (PowerShell)**
```powershell
cd hdews
py -m pip install -r backend\requirements-dev.txt
py -m pip install -r backend\requirements-ml.txt       # optional, see "Windows: Smart App Control" below
Copy-Item .env.example .env                             # then set HDEWS_DEMO_PASSWORD
py scripts\start.py                                     # serves http://127.0.0.1:8000
```

`backend/requirements.txt` holds only what the server needs (Starlette, uvicorn, Pydantic). The ML stack (numpy, pandas, scikit-learn) is used only by the offline evaluation harness in `ml/`.

Sign in with one of the demo accounts (password = `HDEWS_DEMO_PASSWORD`, default `hdews-demo` if unset):

| Account | Can do |
|---|---|
| `reviewer` | Acknowledge, record actions on, and resolve candidate alerts |
| `analyst` | Run the scenario simulator and re-assessments |
| `admin` | Everything, including editing site thresholds |
| `viewer` | Read-only |

Other commands:

| Task | Command |
|---|---|
| Run all backend tests | `cd backend && python -m pytest` |
| Line + branch coverage (stdlib, no plugins) | `python scripts/coverage_report.py` → `docs/coverage.json` |
| Browser end-to-end scenarios A–G | `python e2e/run_e2e.py` (needs Node + Playwright Chromium) → `e2e/results.json` |
| Performance smoke test | `python scripts/perf_smoke.py` → `docs/perf_results.json` |
| Type-check the frontend | `cd frontend && npm run typecheck` |
| Rebuild the frontend | `cd frontend && npm install && npm run build` (pins `typescript` 7.0.2; `./scripts/build_frontend.sh` does the same) |
| Reset and reseed the demo database | `python scripts/reset_db.py` (refuses non-HDEWS files; `--force` to discard observed data) |
| Seed an empty database | `python scripts/seed_demo_data.py` (refused when `HDEWS_ENV=production`) |
| Apply a scenario from the CLI | `python scripts/run_demo_scenario.py rising_landslide_indicators SNP-05` (`--list` for presets) |
| Push a test reading through the ingestion API | `FIELD_GATEWAY_INGEST_KEY=... python scripts/send_sensor_reading.py AGM-03-SOIL 31.2` |
| Run the ML evaluation harness | `python -m ml.evaluate --help` (needs a real labelled dataset) |
| Start the server (any OS) | `python scripts/start.py` (migrates, seeds an empty DB if allowed, serves; `HOST`/`PORT` env) |
| Manage accounts (create, set-password, disable) | `python scripts/manage_users.py --help` (audited; works in production) |
| Run in a container | `docker compose up --build` (needs `HDEWS_DEMO_PASSWORD` in `.env`) |

## 2. Demo walkthrough (the acceptance test)

1. Start the app and sign in as **analyst**. The **Overview** shows the alert queue, a site × hazard matrix of risk chips (tier + reliability bars), sensor connectivity, 24-h rainfall per site and a map preview. The data-mode tag reads *Simulated*.
2. **Live map** — real (approximate) coordinates for six sites along the Mandakini/Alaknanda valleys. Toggle layers, click a marker (or Tab + Enter) to open the site drawer.
3. **Monitoring sites → Sonprayag–Gaurikund Corridor** — sensor cards (value, unit, observed/received time, quality, source, *Simulated* tag), trend charts with demo threshold lines, and an evidence-first risk card per hazard.
4. **Scenario simulator** — choose *Rising landslide indicators* for SNP-05 and apply. The backend regenerates 48 h of simulated telemetry, re-runs the rule engine, and the result table shows **HIGH** with a link to the new candidate alert.
5. Sign out and sign in as **reviewer**. Open the alert: inspect the factors, thresholds, observed times, evidence observations and "Explain in plain language".
6. **Acknowledge** → **Record action** (e.g. field verification, assignee "Field team 2") → **Resolve** with an outcome and reason. Each step uses a confirmation dialog.
7. **Audit log** → *Verify hash chain*: every event, including the alert lifecycle, is listed and the chain verifies.
8. As **analyst**, apply *Sensor outage during adverse weather*. The site shows reliability **POOR**, offline/delayed sensors, a tier marked as a possible underestimate, and *Critical data gap* alerts.
9. **Model & evaluation** shows **Not evaluated yet** — no performance numbers are invented.

This flow is automated in `backend/tests/test_workflow.py` (API level) and was also driven end-to-end in headless Chromium (see §8).

## 3. What makes it different (USP, stated as a hypothesis)

The product hypothesis — to be validated with district disaster-management staff — is that the gap is not "AI + satellite + IoT" (well covered by SILAAS, GSI, NASA LHASA, IIT Mandi and others; see the [original specification](docs/original-specification.md) §3) but an **operational evidence layer**:

* **Risk ≠ reliability.** Every assessment carries a tier *and* a separate reliability grade, shown together in one chip everywhere.
* **Missing data is never "low".** If a critical input is missing or stale and the remaining evidence is benign, the tier is `INSUFFICIENT_DATA`. If the remaining evidence is already adverse, the tier is kept and flagged as a possible underestimate, with the worst-case tier the missing inputs could produce.
* **Evidence-first risk cards** answer what, where, which observations, how fresh, what is missing, what changed, and what a reviewer should check next.
* **Provenance on every value**: `OBSERVED`, `IMPORTED`, `SIMULATED` or `DERIVED`, plus source, observed time and received time.
* **Human-reviewed workflow** with deduplication, state-machine enforcement, mandatory resolution reasons (for false-alarm / missed-event review) and a hash-chained, append-only audit log.
* **Local context**: site-specific thresholds (admin-editable, validated, audited).

## 4. Architecture

A modular monolith. See [docs/architecture.md](docs/architecture.md) for the data flow diagram and module map.

```
Field gateway (push API) ─┐
Scenario simulator ───────┼─► observations (origin, source, observed_at, received_at, quality)
Incident import ──────────┘          │
                                     ▼
            feature extraction (rain 1/3/24 h with coverage, soil moisture, 24 h displacement,
                                river stage + 1 h rise, sensor freshness & delay)
                                     ▼
            baseline rule engine (per hazard) → tier + reliability + factors + evidence ids
                                     ▼
            candidate alerts (dedup) → reviewer actions → resolution → hash-chained audit log
                                     ▼
            REST API (Starlette + Pydantic) → TypeScript SPA (SVG map & charts)
```

| Layer | Implementation |
|---|---|
| API | Starlette 1.7 + Pydantic 2 + uvicorn; structured JSON errors; RBAC; pagination; rate limiting on login/ingestion; security headers |
| Database | SQLite (default, tested). PostgreSQL schema provided and verified to apply on PostgreSQL 16; runtime driver path experimental |
| Risk engine | `backend/app/services/risk_engine/` — pure functions, unit-tested |
| Frontend | TypeScript (strict) compiled with `tsc`, no framework; hand-built Web-Mercator SVG map, SVG charts |
| ML | scikit-learn evaluation harness (`ml/evaluate.py`); pluggable model interface that refuses unvalidated models |
| LLM | Optional explanation assistant (Anthropic API) with a numeric grounding check; template fallback |

### Why not FastAPI / Next.js / Leaflet / Recharts?

They were the preferred stack, but the build environment had **no access to PyPI or npm**, so none of them could be installed or tested. Rather than ship untested code, the prototype uses what was available and verifiable: Starlette (the ASGI framework FastAPI is built on) with Pydantic models, and a framework-free TypeScript UI. Migration is mechanical: route handlers are thin wrappers over services and Pydantic schemas, so moving to FastAPI means re-declaring routes with `APIRouter`; the UI's page modules map one-to-one onto Next.js routes. This is listed under pending work.

## 5. Risk engine (baseline rules `baseline-rules-v0.1-demo`)

Full details: [ml/model_cards/baseline-rules-v0.1.md](ml/model_cards/baseline-rules-v0.1.md).

| Hazard | Indicators (★ = critical) | Points watch / high |
|---|---|---|
| Landslide | ★ rain 24 h; rain 1 h; ★ soil-moisture excess over site baseline; 24 h slope displacement | 1/2; 1/2; 1/2; 2/4 |
| Flash flood | ★ river stage vs site warning/danger stage; 1 h river rise; ★ rain 1 h; rain 3 h | 2/4; 1/2; 1/2; 1/2 |

Score ≥ 4 → HIGH, ≥ 2 → ELEVATED, else LOW. An unavailable input whose sensor is configured at the site is also treated as critical when its data could change the tier, so a sensor outage never lowers the apparent risk. Reliability: POOR if a critical input is missing/stale; DEGRADED if any input is incomplete (<75 % expected samples), delayed (> 2 reporting intervals), suspect, or a non-critical input is missing. If a sensor has readings of several origins (e.g. a real gateway and the simulator), only the highest-precedence origin (observed > imported > simulated) is used for that sensor; series are never summed or differenced across origins. A candidate **hazard** alert is raised at HIGH. A **data-gap** alert is raised when reliability is POOR and conditions are adverse, or when the site's rain gauge is itself unavailable so adverse weather cannot be ruled out. Points are ordinal, **not probabilities**.

## 6. Data

| Data | Origin | Notes |
|---|---|---|
| Sites (6) | Approximate locality coordinates | Simulated monitoring points; no physical sensors installed. `data/sample/sites.json` |
| Sensor telemetry | **SIMULATED** | 15-min interval; the simulated gateway keeps reporting so freshness behaves like a live feed |
| Field-gateway readings | OBSERVED | Via `POST /api/ingestion/FIELD-GATEWAY-01`; none in the seed |
| Incidents (3) | IMPORTED public reports | 2013 Kedarnath flood, 2023 Gaurikund landslide, 2024 Kedarnath-route cloudburst — summaries with source links, **not** cross-checked against an official inventory, no casualty figures |
| Incidents (6) | SYNTHETIC | Titled `[SYNTHETIC]`; describe no real event |
| NASA GPM IMERG, Copernicus DEM, Sentinel-1/2 | Registered, `NOT_CONFIGURED` | Need credentials, processing and licence review — see Data sources page |

Data dictionary: [docs/data-dictionary.md](docs/data-dictionary.md). All timestamps are stored in UTC; the UI displays IST with UTC on hover.

## 7. API

Documented in [docs/api.md](docs/api.md). Main endpoints: `/api/health`, `/api/meta`, `/api/auth/*`, `/api/overview`, `/api/map/layers`, `/api/sites[/{id}[/observations|/assess|/config]]`, `/api/assessments[/{id}[/explanation]]`, `/api/alerts[/{id}[/acknowledge|/actions|/resolve]]`, `/api/incidents`, `/api/data-sources`, `/api/audit-log[/verify]`, `/api/evaluation`, `/api/rules`, `/api/demo/presets`, `/api/demo/scenario` (disabled when `HDEWS_ENV=production`), `/api/ingestion/{source_id}`.

## 8. Verification performed

A full audit, repair and test pass was carried out on 2026-10-28 in two passes. The second pass independently re-verified
the first. See [docs/BUG_AUDIT_REPORT.md](docs/BUG_AUDIT_REPORT.md), [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md),
[docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md) and [docs/TEST_PLAN.md](docs/TEST_PLAN.md). In short:

* **36 confirmed defects**, each reproduced before fixing: 35 fixed and verified, and 1 (PostgreSQL audit-chain locking) fixed but unverifiable here. They include a Critical production default-credential issue and 7 High-severity defects, among them safety defects in the risk engine and alerting: double-counted rainfall, observed and simulated series combined into a false HIGH, stale values shown as current, outages lowering apparent risk, and a total blackout raising no alert. **No threshold or point value was changed.**
* A third, deployment-readiness pass (2026-10-29) fixed **9 more defects**: no safe hosted mode (High), the whole test suite aborting when Windows blocks pandas, Windows text-encoding corruption of the seed data, rate limits shared by all users behind a proxy, an unvalidated `HDEWS_ENV`, and container issues.
* Backend: **489 tests pass, 1 skipped** (PostgreSQL driver unavailable). The same result was obtained under a Windows-style cp1252 locale. Browser E2E scenarios A–G: **93/93 checks**. Coverage of the risk engine: 99.8 % lines. Exact numbers, commands and limitations are in `docs/TEST_RESULTS.md`.
* A passing test suite verifies the software; it does **not** validate HDEWS as a disaster-prediction or official early-warning system.

## 9. Testing

```bash
cd backend && python -m pytest                     # full backend suite (~2 min)
cd backend && python -m pytest tests/test_risk_engine.py tests/test_risk_engine_boundaries.py   # risk engine only
python scripts/coverage_report.py                  # line + branch coverage (stdlib; coverage.py not required)
python scripts/perf_smoke.py --days 30             # performance smoke test on a temporary database
python e2e/run_e2e.py --shots /tmp/hdews-shots     # browser E2E A-G (needs Node + Playwright + Chromium)
python docs/evidence/second_pass_verify_claims.py .   # re-run the defect reproductions
```
Every test uses an in-memory or temporary database; none touches `backend/hdews.db`.

## 10. Feature status

**Implemented and tested:** role-based login (demo accounts), overview, interactive map with layers/legend/drawer, site pages with sensor health and charts, landslide and flash-flood baseline engine, evidence cards with change tracking, insufficient-data and lower-bound logic, candidate alert lifecycle with dedup and state enforcement, data-gap alerts, hash-chained append-only audit log, scenario simulator (5 presets + custom inputs + connectivity/delay), continuing simulated telemetry, authenticated idempotent ingestion API, data-source registry with derived health, historical incident explorer (search, filters, timeline, map), evaluation page with honest "Not evaluated yet", evaluation harness, admin threshold editor, template explanations, optional grounded LLM explanations, responsive layout.

**Simulated / demo-only:** all sensor telemetry, hazard-zone buffers, pilot-area box, schematic river lines, synthetic incidents, demo playbook (not an approved SOP), demo user accounts, "test notification" actions (recorded, never sent).

**Pending / not implemented:** FastAPI + Next.js port; PostgreSQL runtime path under test (needs `psycopg`; migrations 001–005 verified with `psql` on PostgreSQL 16); PostGIS; real NASA IMERG / Copernicus / IMD adapters; any validated ML model (needs a labelled event inventory); calibrated thresholds; real identity provider; SMS/CAP/SACHET integration (out of scope without authorisation); Docker image build (files written, not built); offline/PWA capability; multi-language alert templates.

**Requires credentials or data:** `LLM_API_KEY` (optional explanations; the live call was not exercised — only the grounding logic with a mocked provider), NASA Earthdata account, Copernicus Data Space account, an authorised labelled landslide/flood inventory, physical gateway hardware.

## 11. Deploying

The whole application is **one Python process**: it serves the API, the compiled frontend (same origin, so no CORS) and the background telemetry/assessment loop, with a **SQLite database on persistent storage**. There is no GPU or ML inference at runtime: the ML harness is an offline tool and is not installed in the image.

**Recommended:** GitHub (source + Actions) → Render web service built from the `Dockerfile`, on a paid instance with a 1 GB persistent disk (`render.yaml`). Full steps, costs and alternatives are in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Key points:

* `HDEWS_ENV=demo` is the hosted mode: simulator on, a strong `HDEWS_DEMO_PASSWORD` is **required** (start-up refuses defaults or anything under 12 characters), and secrets are never printed to logs.
* Do **not** use GitHub Pages (it cannot run the Python backend) or a free Render instance (it spins down after 15 idle minutes and loses the SQLite file on every restart or deploy).
* CI (`.github/workflows/ci.yml`) runs the backend tests on Linux and Windows, checks that `frontend/dist` matches `frontend/src`, builds and smoke-tests the Docker image, runs the browser E2E suite, and only then calls the Render deploy hook on `main`.
* A hosted instance is still a **research prototype with simulated data**. Do not present it as a public warning service.

## 12. Troubleshooting

* **Windows: `ImportError: DLL load failed while importing nattype: An Application Control policy has blocked this file.`**
  Windows **Smart App Control** or **App Control for Business (WDAC)** refused to load pandas' compiled extension. It is not
  Authenticode-signed (Windows error 4551). This is a Windows security policy decision, not a broken or incompatible package,
  and it only affects the optional ML harness: the server never imports pandas. Since this release the backend test suite
  skips only `tests/test_ml_harness.py` and prints this reason; previously the whole run was interrupted. To confirm the cause,
  open *Windows Security → App & browser control → Smart App Control*, or look in *Event Viewer → Applications and Services
  Logs → Microsoft → Windows → CodeIntegrity → Operational* for the blocked `.pyd` file. **Do not turn off Smart App Control
  for this.** To run the ML harness, use WSL 2, the Docker image with the ML requirements added, or the GitHub Actions run
  (Linux and Windows runners there execute it), or ask your administrator about an approved policy.

* *"Database already seeded"* — run `python scripts/reset_db.py` to start over.
* *Everything shows "Insufficient data"* — the server was stopped for a while, so simulated sensors went stale (by design). Keep the server running a minute (the background loop catches up) or click *Re-run assessment*.
* *Map has no basemap* — tiles are optional and need internet; tick *Online basemap* on the Live map page.
* *401 on ingestion* — the key must match `FIELD_GATEWAY_INGEST_KEY` at seed time; reset the DB after changing it.
* *Port in use* — set `PORT=8010` (any OS) before `python scripts/start.py`.
* *"HDEWS start-up refused"* — the message says why (e.g. `HDEWS_ENV=demo` without a strong `HDEWS_DEMO_PASSWORD`, an unknown `HDEWS_ENV`, or default passwords on a hosted instance). Nothing is served until it is fixed.
* *"Refusing to reset"* — `reset_db.py` only deletes HDEWS databases and keeps observed data unless `--force` is given. Back the file up first.
* *"Refusing to start in production"* — an active account still uses a documented demo password. Disable it or change the password; the demo seed cannot be used in production.
* *A landslide site shows "Insufficient data" in normal weather* — a sensor configured at that site is unavailable (e.g. UKM-06's extensometer is in maintenance). By design, LOW is never claimed while configured evidence that could contradict it is missing.
* *A sensor went stale after I pushed a test reading* — once a sensor has observed readings, only those are used (they take precedence over simulated ones). If no further observed readings arrive, the sensor is correctly shown stale until the test reading leaves the 26 h window. Use the simulator's sites for demos, or keep pushing readings.
* *Gateway readings rejected as "outside this source's site scope"* — check or set the scope: `python scripts/set_ingest_scope.py FIELD-GATEWAY-01 [SITE ...]`.
* *405 "method not allowed"* — the endpoint exists but not for that HTTP method; see the `Allow` header and `docs/api.md`.

## 13. Repository layout

```
backend/app/        Starlette app: api/, services/ (risk_engine, alerts, assessments, simulator, ingestion, audit, explanations), migrations/
backend/tests/      pytest suites
frontend/src/       TypeScript SPA (pages/, map.ts, charts.ts, dom.ts)   frontend/dist/  compiled build
ml/                 evaluate.py harness, model_cards/
data/sample/        sites.json, incidents.json (documented demo data)
docs/               architecture, api, data dictionary, safety, evaluation plan, original specification
scripts/            run_dev.sh, seed/reset, scenario CLI, ingestion test client, frontend build
```
