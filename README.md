# HDEWS — Himalayan Disaster Early Warning System (prototype)

**From environmental signals to explainable, human-reviewed early action.**

HDEWS is a working decision-support prototype for rainfall-triggered landslide and flash-flood risk in a pilot study area in **Rudraprayag district, Uttarakhand**. It ingests sensor observations, computes transparent hazard assessments that keep *risk* and *data reliability* separate, raises candidate alerts for authorised human review, and records every decision in a tamper-evident audit log.

> **Safety boundary.** HDEWS is a research prototype. It is **not** a certified or official warning service. All sensor telemetry in the demo is **SIMULATED**; thresholds are **uncalibrated demonstration settings**; candidate alerts are internal review items and **nothing is ever sent to the public**. Follow the responsible authority's approved SOPs. See [docs/safety-and-limitations.md](docs/safety-and-limitations.md).

---

## 1. Quick start

Prerequisites: **Python 3.11+** (tested on 3.13). Node is only needed to rebuild the frontend (`tsc`); a compiled build is included in `frontend/dist`.

```bash
cd hdews
pip install -r backend/requirements.txt
cp .env.example .env              # then set HDEWS_DEMO_PASSWORD and FIELD_GATEWAY_INGEST_KEY
./scripts/run_dev.sh              # builds the UI if needed, seeds the DB on first run, serves http://127.0.0.1:8000
```

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
| Run all tests | `cd backend && python -m pytest` |
| Reset and reseed the database | `python scripts/reset_db.py` |
| Seed an empty database | `python scripts/seed_demo_data.py` |
| Apply a scenario from the CLI | `python scripts/run_demo_scenario.py rising_landslide_indicators SNP-05` (`--list` for presets) |
| Push a test reading through the ingestion API | `FIELD_GATEWAY_INGEST_KEY=... python scripts/send_sensor_reading.py AGM-03-SOIL 31.2` |
| Rebuild the frontend | `./scripts/build_frontend.sh` (needs `tsc` ≥ 5) |
| Run the ML evaluation harness | `python -m ml.evaluate --help` (needs a real labelled dataset) |
| Start the server manually | `uvicorn app.main:factory --factory --app-dir backend --port 8000` |

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

Score ≥ 4 → HIGH, ≥ 2 → ELEVATED, else LOW. Reliability: POOR if a critical input is missing/stale; DEGRADED if any input is incomplete (<75 % expected samples), delayed (> 2 reporting intervals), suspect, or a non-critical input is missing. A candidate **hazard** alert is raised at HIGH; a **data-gap** alert is raised when reliability is POOR during adverse conditions. Points are ordinal, **not probabilities**.

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

* **41 automated tests pass** (`cd backend && python -m pytest`): 15 risk-engine unit tests, 14 API tests (auth, RBAC, validation, pagination, ingestion, production lock-down), 8 workflow tests (scenario → alert → review → audit, dedup, outage, stale data recovery, append-only audit, LLM grounding), 4 ML-harness tests.
* **PostgreSQL schema** applied cleanly to PostgreSQL 16 with `psql`, including the append-only trigger.
* **Headless Chromium walkthrough** of the full acceptance journey (login → overview → map → site → simulator → reviewer acknowledge/act/resolve → audit verification → outage scenario → evaluation, incidents, sources, alerts, settings, mobile viewport) completed with **zero console errors**.

## 9. Feature status

**Implemented and tested:** role-based login (demo accounts), overview, interactive map with layers/legend/drawer, site pages with sensor health and charts, landslide and flash-flood baseline engine, evidence cards with change tracking, insufficient-data and lower-bound logic, candidate alert lifecycle with dedup and state enforcement, data-gap alerts, hash-chained append-only audit log, scenario simulator (5 presets + custom inputs + connectivity/delay), continuing simulated telemetry, authenticated idempotent ingestion API, data-source registry with derived health, historical incident explorer (search, filters, timeline, map), evaluation page with honest "Not evaluated yet", evaluation harness, admin threshold editor, template explanations, optional grounded LLM explanations, responsive layout.

**Simulated / demo-only:** all sensor telemetry, hazard-zone buffers, pilot-area box, schematic river lines, synthetic incidents, demo playbook (not an approved SOP), demo user accounts, "test notification" actions (recorded, never sent).

**Pending / not implemented:** FastAPI + Next.js port; PostgreSQL runtime path under test (needs `psycopg`); PostGIS; real NASA IMERG / Copernicus / IMD adapters; any validated ML model (needs a labelled event inventory); calibrated thresholds; real identity provider; SMS/CAP/SACHET integration (out of scope without authorisation); Docker image build (files written, not built); offline/PWA capability; multi-language alert templates.

**Requires credentials or data:** `LLM_API_KEY` (optional explanations; the live call was not exercised — only the grounding logic with a mocked provider), NASA Earthdata account, Copernicus Data Space account, an authorised labelled landslide/flood inventory, physical gateway hardware.

## 10. Troubleshooting

* *"Database already seeded"* — run `python scripts/reset_db.py` to start over.
* *Everything shows "Insufficient data"* — the server was stopped for a while, so simulated sensors went stale (by design). Keep the server running a minute (the background loop catches up) or click *Re-run assessment*.
* *Map has no basemap* — tiles are optional and need internet; tick *Online basemap* on the Live map page.
* *401 on ingestion* — the key must match `FIELD_GATEWAY_INGEST_KEY` at seed time; reset the DB after changing it.
* *Port in use* — `PORT=8010 ./scripts/run_dev.sh`.

## 11. Repository layout

```
backend/app/        Starlette app: api/, services/ (risk_engine, alerts, assessments, simulator, ingestion, audit, explanations), migrations/
backend/tests/      pytest suites
frontend/src/       TypeScript SPA (pages/, map.ts, charts.ts, dom.ts)   frontend/dist/  compiled build
ml/                 evaluate.py harness, model_cards/
data/sample/        sites.json, incidents.json (documented demo data)
docs/               architecture, api, data dictionary, safety, evaluation plan, original specification
scripts/            run_dev.sh, seed/reset, scenario CLI, ingestion test client, frontend build
```
