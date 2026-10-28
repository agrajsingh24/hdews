# HDEWS — Himalayan Disaster Early Warning System
### Research-backed concept, product USP, technical architecture, and AI-agent prototype specification

> **Core principle:** AI as Sentinel, Human as Commander.  
> HDEWS is a proposed disaster-intelligence and early-action platform for Himalayan regions. It combines environmental observations, ground sensors, geospatial context, risk-analysis models, transparent evidence, and human-reviewed alert workflows.

---

## 1. Executive Summary

Himalayan communities face landslides, flash floods, extreme rainfall, glacial-lake hazards, forest fires, and other interconnected risks. Data may exist across weather services, satellite products, river gauges, ground sensors, terrain maps, and historical event records, but it is not always presented in one operational view.

HDEWS aims to turn heterogeneous environmental data into **location-specific, traceable risk assessments and actionable workflows** for disaster-management teams.

The first prototype should be deliberately narrow:
- Primary hazards: **rainfall-triggered landslide risk and flash-flood risk**.
- Pilot geography: a clearly defined study area in Uttarakhand, selected according to data availability.
- Demonstration: live or simulated sensor telemetry, a real satellite-derived or historical geospatial layer, a transparent risk engine, a map dashboard, an alert log, and human review.
- Safety boundary: the prototype is a decision-support demonstrator, **not an officially certified warning service**.

### Product positioning

**HDEWS is a Himalayan-focused, evidence-first disaster intelligence platform that connects regional environmental signals with local sensor conditions and a human-reviewed early-action workflow.**

Do not claim that it is the first system of its kind, that it can predict every disaster, or that it guarantees a fixed warning lead time. Those claims require evidence and independent validation.

---

## 2. The Real-World Problem

### 2.1 What is difficult today?

1. **Fragmented observations:** rainfall, soil moisture, slope movement, satellite-derived changes, terrain, and incident records may be managed in different systems.
2. **Different spatial and temporal scales:** satellite products cover broad areas but may not update continuously; ground sensors provide local readings but cover limited locations.
3. **Remote connectivity:** high-altitude areas may have unreliable power, mobile coverage, and backhaul connectivity.
4. **Uncertainty:** a sensor spike, heavy rainfall, or an image change alone does not prove that a disaster will occur.
5. **Operational follow-through:** a useful warning must identify where the concern is, why it was raised, how fresh the evidence is, who should review it, and what action is appropriate.
6. **Last-mile communication:** residents may not have internet access or smartphones; official warning channels and local protocols matter.
7. **Trust and false alarms:** excessive alerts can cause warning fatigue, while missed events can have serious consequences.

### 2.2 The proposed solution

HDEWS should create a shared operational picture by:
- Ingesting data from configured sources.
- Recording source, timestamp, location, quality, and freshness.
- Combining hazard-specific indicators with terrain and historical context.
- Producing an interpretable risk level with explicit limitations.
- Showing the evidence behind each risk assessment.
- Routing candidate alerts to authorised reviewers.
- Recording acknowledgements, decisions, and actions.
- Remaining useful when a data source becomes stale or unavailable.

---

## 3. Research and Existing-System Landscape

This is a focused desk-research snapshot, not a complete systematic literature review. Recheck source documentation, licences, APIs, and current deployments before implementation or public claims.

### 3.1 Relevant initiatives and what they imply

| Existing initiative | Publicly described focus | Implication for HDEWS |
|---|---|---|
| **SILAAS / USAC / NRSC–ISRO** | Uttarakhand's Satellite Integrated Landslide Assessment and Alert System includes landslide inventory work using satellite imagery and DEMs, with field verification. | Satellite imagery + terrain analysis is already an active area. Differentiate through operational integration, data-quality visibility, local sensor fusion, and action tracking—not satellite imagery alone. |
| **GSI landslide early-warning work** | GSI describes collaborations for regional and site-specific landslide monitoring/forecasting, including rainfall and landslide data. | HDEWS should complement, not claim to replace, specialist geological forecasts or official products. |
| **USDMA Vasundhara Tal installation (2026)** | USDMA reports a first installation phase for sensor-based monitoring around a glacial lake, with satellite communication for a remote setting. | Remote telemetry, communications resilience, and glacial-lake monitoring are already being addressed. Treat GLOF monitoring as a future module requiring domain-specific data and expert validation. |
| **NASA LHASA** | NASA describes a landslide hazard model using satellite-derived precipitation and soil moisture alongside slope, geology, and earthquake-risk information. | Multi-source geospatial hazard assessment is established research. HDEWS can focus on regional workflow, local sensor corroboration, evidence provenance, and field operations. |
| **NDMA SACHET / CAP alerting** | Geo-targeted, multi-channel disaster-alert dissemination, including SMS, mobile, browser notifications, and CAP-related feeds. | HDEWS should not recreate official national alerting. Prototype notifications should be clearly marked as test alerts; future integration would require authorised interfaces and approvals. |
| **IIT Mandi / sensor-based landslide systems** | Public descriptions discuss sensor networks and ML-assisted landslide alerts in Himalayan locations. | Low-cost sensors and ML are not a unique USP by themselves. Focus on a measurable integration and operational gap. |
| **ISRO disaster-management support / NDEM** | Space-based inputs and geospatial decision-support information support disaster preparedness and response. | Design HDEWS as a complementary local intelligence and workflow layer, not a replacement for national geospatial infrastructure. |

### 3.2 Research links

1. Uttarakhand IT Department — [SILAAS overview](https://it.uk.gov.in/scheme/satellite-integrated-landslide-assessment-and-alert-system-silaas/)
2. Geological Survey of India — [Landslide hazard and early-warning work](https://gsi.gov.in/landslide-hazard/)
3. Uttarakhand State Disaster Management Authority — [Vasundhara Tal early-warning installation, 2026](https://usdma.uk.gov.in/14-sep-2026-usdma-successfully-completes-first-phase-of-early-warning-system-installation-at-vasundhara-tal/)
4. NASA Science — [Assessing Landslide Hazards From Space](https://science.nasa.gov/blogs/notes-from-the-field/2025/08/29/assessing-landslide-hazards-from-space/)
5. NDMA — [SACHET National Disaster Alert Portal](https://sachet.ndma.gov.in/)
6. Ministry of Home Affairs — [National Database for Emergency Management (NDEM)](https://www.mha.gov.in/scheme/national-database-emergency-management-ndem-portal)
7. ISRO — [Space Applications and disaster-management work](https://www.isro.gov.in/SpaceApplications.html)
8. NITI Aayog Frontier Tech — [Low-cost sensors and AI for Himalayan landslide alerts](https://frontiertech.niti.gov.in/story/low-cost-indigenous-sensors-ai-deliver-real-time-landslide-alerts-across-himalayan-slopes/)
9. Liu et al. (2024) — [Comparative study of regional rainfall-induced landslide warning models using RF, CNN, and MLP](https://www.frontiersin.org/journals/earth-science/articles/10.3389/feart.2024.1419421/full)

### 3.3 Research conclusion

The broad concept is valuable, but **“AI + satellite + IoT for disaster prediction” is not sufficiently unique on its own**. Existing public initiatives cover important parts of this space.

The strongest product opportunity is a **transparent, data-quality-aware, local decision-support layer** that:
- Brings different sources into a common geospatial and temporal view.
- Explicitly distinguishes observed, delayed, missing, simulated, and model-derived information.
- Explains which factors changed a risk assessment.
- Uses site-specific context rather than one universal threshold.
- Turns a candidate risk signal into a traceable human review and action workflow.
- Keeps operating in degraded-data conditions without pretending uncertainty has disappeared.

This is a proposed differentiation hypothesis, not proof of market uniqueness. Validate it through interviews with district disaster-management staff, field teams, geospatial researchers, and intended users.

---

## 4. USP and Differentiation

### Recommended primary USP

**“From environmental signals to explainable, human-reviewed early action—built for the data and connectivity realities of Himalayan terrain.”**

### Product pillars

#### A. Multi-source evidence fusion
Combine selected satellite-derived data, weather/rainfall information, terrain context, historical incidents, and local sensor readings in one timeline and map.

#### B. Evidence-first risk cards
Every risk card should answer:
- What hazard and location are being assessed?
- Which observations support the assessment?
- When were those observations collected?
- Which sources are missing or stale?
- What changed since the previous assessment?
- What is the model's confidence or uncertainty, and how was it measured?
- What should an authorised reviewer inspect next?

#### C. Data-health and uncertainty layer
Show sensor heartbeat, last-seen time, missing values, quality flags, satellite acquisition date, source delay, and connectivity state. If evidence is inadequate, return **“Insufficient data”** rather than an invented risk percentage.

#### D. Local context, not one-size-fits-all thresholds
Allow site-specific configuration for terrain, sensor placement, local baseline, rainfall history, and validated operating thresholds. Initial prototype thresholds must be labelled as demonstration rules unless calibrated with real data.

#### E. Early-action workflow
Candidate alert → reviewer triage → acknowledgement → decision → assigned action → closure and audit trail. The system should support action, not automatically issue evacuation orders.

#### F. Resilient and accessible design
Responsive interface, low-bandwidth-friendly views, language-ready alert templates, and offline/queued event capture where feasible. Real SMS, sirens, satellite links, and official integrations require services, hardware, permissions, and testing.

### What should not be claimed as a USP
- “World's first” or “India's first” without a defensible novelty review.
- “100% accurate” or “predicts every disaster.”
- A guaranteed number of hours of warning without validated event-level testing.
- “Real-time satellite monitoring” unless the selected product genuinely has that update cadence.
- Official agency integration, deployments, partnerships, or certifications that do not exist.

---

## 5. Prototype Scope: Build One Complete Workflow

### Included in MVP

1. **Role-aware demo login:** administrator, analyst, reviewer. If authentication is mocked, label it as demo-only.
2. **Risk overview:** counts by risk tier, active candidate alerts, data freshness, sensor status, recent incidents.
3. **Interactive map:** pilot-area boundary, monitored sites, hazard zones, sensor markers, risk state, and layer toggles.
4. **Site detail page:** rainfall, soil moisture, displacement/tilt (where available), recent trends, location context, last-seen status, and source provenance.
5. **Risk engine:** deterministic, documented baseline rules first; pluggable ML inference interface for a later validated model.
6. **Candidate alert workflow:** create, inspect evidence, acknowledge, escalate for review, mark action, resolve, and view history.
7. **Historical event explorer:** past incidents and time-series comparison when a suitable dataset is available.
8. **Data simulator:** adjustable rainfall, soil moisture, slope movement, river level, sensor delay, and outage scenarios.
9. **Data-source status:** clearly distinguish real, imported, simulated, stale, and unavailable data.
10. **Audit trail:** record every generated candidate alert and every human decision.
11. **Safety and limitations panel:** explain prototype status and prohibit the UI from presenting demo outputs as official warnings.

### Explicitly out of scope for MVP

- Certified emergency-warning service.
- Autonomous evacuation, road closure, rescue dispatch, or public emergency declarations.
- Unsupported claims of calibrated probabilities.
- All-hazard forecasting in one model.
- Custom foundation-model training.
- Full drone fleet, satellite tasking, or field sensor deployment.
- Production SMS/siren/satellite communications without approved providers and operational procedures.
- GLOF or earthquake prediction without specialist data and validated methods.

### Suggested pilot area

Choose one well-defined study area based on available event records, terrain layers, and rainfall data. Rudraprayag is a possible research candidate because GSI has described experimental rainfall-induced landslide forecasting work there; the team must verify current data access and suitability before choosing it. Do not imply an official partnership.

---

## 6. Data Strategy

The prototype must work even if live APIs or physical sensors are unavailable. Use adapters so data sources can be swapped without rewriting the application.

### Candidate data sources to investigate

| Data type | Potential source | Use | Important limitation |
|---|---|---|---|
| Rainfall / precipitation | NASA GPM IMERG; authorised IMD products where accessible | Rainfall accumulation and intensity features | Spatial resolution, update latency, licensing, and access must be checked. Gridded precipitation is not a substitute for every local rain gauge. |
| Satellite optical imagery | Copernicus Sentinel-2; other suitable open imagery | Land cover, water-body, and change context | Cloud cover and revisit timing can limit usefulness; optical imagery alone cannot reliably predict an imminent landslide. |
| Radar imagery | Copernicus Sentinel-1, subject to data availability | Surface-change and deformation analysis with specialist processing | Requires geospatial expertise; terrain, vegetation, coherence, and revisit limitations matter. |
| Terrain | Copernicus DEM or other appropriately licensed DEM | Slope, aspect, elevation, drainage and terrain context | DEM resolution and errors affect derived features. |
| Weather forecasts | Official/authorised forecast services | Forecast rainfall and weather context | Do not scrape or redistribute restricted services; confirm terms and timestamps. |
| Ground sensors | ESP32/Arduino or commercial telemetry gateway for a lab prototype | Local rainfall, moisture, tilt/displacement, river-level signals | Cheap hobby sensors are not safety-certified instruments; calibration and field engineering are essential. |
| Historical events | Official incident inventories, research datasets, documented reports | Labels, evaluation and historical context | Reporting bias, incomplete locations, event-time uncertainty, and licensing may affect evaluation. |
| River/hydrology | Authorised gauges or open datasets where suitable | Water-level trends and flood indicators | Gauge coverage is sparse; data access and time alignment need verification. |

### Data-source requirements

Every observation should include:
- `source_id`
- `observed_at` (UTC timestamp)
- `received_at` (UTC timestamp)
- latitude/longitude or spatial geometry
- value and unit
- quality/status flag
- real/simulated/imported designation
- source URL or dataset/version reference when allowed
- processing version where derived

Do not call a data feed “live” unless the UI can show its actual last-update time and source.

---

## 7. AI and Analytics: Practical Model Choices

**Do not start by training a deep-learning model from scratch.** First build reliable ingestion, baseline logic, evidence display, and evaluation.

### Stage 1 — Transparent baseline

Implement hazard-specific rule/score logic using configurable, documented thresholds. Use synthetic data only for UI and pipeline testing. Make the rules visible in code and explain them in the interface. Never treat demo thresholds as operational guidance.

Example concept (not an operational threshold):
- rainfall trend increases;
- soil moisture is unusually high relative to a site baseline;
- movement sensor exceeds a site-configured change threshold;
- one or more sources are stale or missing.

The output should include a risk tier, contributing signals, missing evidence, and timestamp. If critical inputs are unavailable, use `insufficient_data` or reduce the reliability status instead of fabricating certainty.

### Stage 2 — Tabular ML benchmark

Once appropriately labelled historical data is available, compare:
- Logistic Regression as a simple baseline.
- Random Forest.
- XGBoost or another gradient-boosted tree model, if dependencies and licences suit the project.

Potential features:
- rolling rainfall totals and intensity;
- antecedent rainfall windows;
- soil moisture level and rate of change;
- tilt/displacement change and rate;
- slope, aspect, elevation, geology/land-cover features when available;
- forecast rainfall;
- sensor-quality and missingness indicators.

Labels must be defined with domain experts. Avoid leakage from measurements recorded after the event. Use temporal and spatial holdouts rather than random row splits alone. Evaluate precision, recall, PR-AUC, false alarms, missed events, lead time, and calibration when estimating probabilities.

### Stage 3 — Time-series models

Only if there is sufficient high-frequency, quality-controlled, labelled sensor history, compare models such as gradient-boosted features over rolling windows, Random Forest, or temporal neural models (e.g. LSTM/Temporal CNN). A neural network is not automatically better than a simpler baseline.

### Satellite / computer vision

For the MVP, use existing derived products and standard geospatial processing where possible. If a specific image-classification or change-detection task is justified:
- establish a labelled dataset and ground truth;
- benchmark a simple baseline;
- evaluate by region and season;
- document cloud, resolution, and revisit limitations.

Do not infer an imminent landslide merely from a visually changed satellite image.

### LLM role

Use an LLM only as a **grounded explanation and summarisation assistant**, not the numerical disaster-prediction engine.

It may:
- turn structured model evidence into a concise explanation;
- summarise incident logs;
- generate draft checklists from an approved playbook;
- answer questions about recorded observations with source citations.

It must not:
- invent measurements, probabilities, or lead times;
- generate or issue official warnings autonomously;
- override the deterministic/ML risk engine;
- provide evacuation instructions beyond approved, configured guidance;
- hide missing or stale data.

All LLM output should be labelled as an explanation generated from recorded evidence and should link back to the underlying observations.

---

## 8. Recommended Technical Architecture

Use a modular monolith for the prototype. Avoid microservices until there is a demonstrated need.

### Suggested stack

- **Frontend:** Next.js + TypeScript + Tailwind CSS + a reusable component library.
- **Map:** MapLibre GL JS or Leaflet; use a suitable basemap provider and respect its terms.
- **Charts:** Recharts or another maintained chart library.
- **Backend API:** Python FastAPI.
- **Data validation:** Pydantic.
- **Database:** PostgreSQL; add PostGIS if spatial queries are needed.
- **Time-series storage:** PostgreSQL initially; TimescaleDB is optional if justified.
- **Jobs:** simple scheduled/background jobs first; add a queue only when necessary.
- **Geospatial processing:** GeoPandas, Rasterio, xarray, and GDAL where required.
- **ML:** scikit-learn first; XGBoost or PyTorch only for a justified experiment.
- **Testing:** pytest, API integration tests, and frontend component/e2e tests.
- **Deployment:** Docker Compose for local reproducibility; choose a hosting environment only after checking geospatial and database needs.

Versions should be pinned in project manifests and updated after compatibility checks. Do not hardcode credentials in source control.

### Logical flow

```text
Satellite / Weather / Historical Data / IoT
                    |
                    v
         Source Adapters + Validation
                    |
                    v
     Timestamp / Geo-Reference / Quality Flags
                    |
                    v
       Feature Processing + Data Storage
                    |
                    v
     Hazard-Specific Baseline / ML Interface
                    |
                    v
   Risk Tier + Evidence + Uncertainty + Freshness
                    |
                    v
       Map Dashboard + Site Detail + Timeline
                    |
                    v
       Candidate Alert + Human Review Queue
                    |
                    v
       Acknowledgement / Action / Audit Trail
```

### Core backend entities

- `User`: id, display name, role, status.
- `Site`: id, name, district, coordinates, hazard types, configuration.
- `Sensor`: id, site id, type, unit, status, last seen.
- `Observation`: id, source id, site id, observed time, received time, value, unit, quality, provenance, simulated flag.
- `HazardAssessment`: id, site id, hazard type, risk tier, reliability status, evidence summary, model version, assessed time.
- `CandidateAlert`: id, assessment id, severity, status, created time, reviewer, decision, resolution.
- `ActionLog`: id, alert id, actor, action, notes, timestamp.
- `DataSource`: id, source name, source type, access mode, last successful update, health status.
- `Incident`: id, hazard, location, event time, source, verification status, notes.

Use migrations and relational constraints. Record timestamps in UTC and display local time consistently in the UI.

---

## 9. Alert Lifecycle and Safety Rules

Recommended lifecycle:

`NORMAL → WATCH → REVIEW_REQUIRED → ACKNOWLEDGED → ACTION_ASSIGNED → RESOLVED`

A critical state can be added only after defining its meaning and review process. The prototype may also use `INSUFFICIENT_DATA`, `STALE_DATA`, and `SENSOR_OFFLINE` as data-quality states; these are not hazard levels.

Rules:
1. Every alert references the assessment and observations that produced it.
2. Duplicate alerts should be deduplicated or grouped rather than spamming reviewers.
3. A stale sensor must be visibly stale; it must not be displayed as a current reading.
4. The interface must separate **risk level** from **data reliability**.
5. A model-generated candidate is not an official public warning.
6. Only authorised people can acknowledge, escalate, resolve, or publish an alert.
7. All decisions and changes must be auditable.
8. Test mode must be visually unmistakable and never send real emergency messages.
9. Include false-positive and missed-event review in the evaluation workflow.
10. Emergency procedures must follow the relevant authorities' approved SOPs.

---

## 10. Prototype UI Specification

Create a polished, credible operational dashboard—not a generic startup landing page.

### Main navigation
- Overview
- Live Map
- Monitoring Sites
- Candidate Alerts
- Historical Events
- Data Sources
- Model & Evaluation
- Audit Log
- Settings

### Overview
- Pilot area and current data mode (real/imported/simulated).
- Active candidate alerts by tier.
- Sites online/offline/stale.
- Recent observation timeline.
- Risk trend chart with clear units and timestamps.
- Map preview with site markers.
- A visible prototype/simulation label when applicable.

### Live Map
- Terrain/base map.
- Toggleable layers: monitored sites, hazard zones, rainfall/context, incidents.
- Click marker to open a site detail drawer.
- Legend and accessible colours/icons.
- Layer metadata and observation date.
- Empty/error/loading states.

### Monitoring Site
- Site name, coordinates, hazard focus, data mode.
- Sensor cards with values, units, last-seen timestamps and health.
- Time-series charts.
- Risk assessment and contributing factors.
- Missing data and uncertainty.
- Related incidents and alert history.

### Candidate Alert Detail
- Hazard, location, risk tier and reliability state.
- Generated timestamp and last data update.
- Evidence list with source and observed time.
- Why the assessment changed.
- Approved next-step checklist.
- Reviewer actions and audit history.
- Strong warning that a demo alert is not an official warning.

### Model & Evaluation
- Dataset provenance and version.
- Train/validation/test date and region split.
- Event count and class balance.
- Precision, recall, PR-AUC, false alarms, missed events, and lead-time analysis where supported.
- Calibration plot only if probability calibration is performed.
- Limitations and known failure cases.
- Clearly mark “not evaluated” where no valid test data exists.

---

## 11. API Design (Suggested)

- `GET /api/health`
- `GET /api/overview`
- `GET /api/sites`
- `GET /api/sites/{site_id}`
- `GET /api/sites/{site_id}/observations`
- `GET /api/map/layers`
- `GET /api/assessments`
- `GET /api/alerts`
- `GET /api/alerts/{alert_id}`
- `POST /api/alerts/{alert_id}/acknowledge`
- `POST /api/alerts/{alert_id}/actions`
- `POST /api/alerts/{alert_id}/resolve`
- `GET /api/data-sources`
- `GET /api/audit-log`
- `POST /api/demo/scenario` (development/demo only; disabled in production)
- `POST /api/ingestion/{source_id}` (authenticated ingestion endpoint)

Use pagination, validation, structured errors, access control, and request logging. Never expose the demo scenario endpoint publicly in production.

---

## 12. Evaluation Plan

A good prototype should demonstrate functionality and honest measurement—not just visual polish.

### Functional acceptance criteria
- The app launches locally from documented commands.
- A seeded demo dataset loads reliably.
- Real, imported, and simulated observations are visually distinguished.
- Site markers and detail views work.
- Changing a demo sensor value updates the assessment and evidence explanation.
- Missing/stale sensor scenarios produce visible data-quality states.
- Candidate alerts can be reviewed, acknowledged, actioned, and resolved.
- The audit trail records changes.
- The application never presents a demo risk score as a validated disaster probability.
- Automated tests cover the main risk and alert lifecycle.

### Model evaluation
When suitable labelled data exists:
- Use temporal and geographic holdouts.
- Compare against a simple baseline.
- Report precision, recall, PR-AUC, false-alarm rate, missed-event rate, and event lead time where possible.
- Report uncertainty and calibration if probabilities are shown.
- Include performance by site/region and season where sample sizes permit.
- Document dataset gaps and class imbalance.
- Do not claim operational readiness based on a synthetic demo.

### Human usability
Test with intended users, if access is available:
- Can they identify the affected location quickly?
- Can they understand why an alert was generated?
- Can they distinguish stale data from low risk?
- Can they complete the review workflow?
- Are recommended next steps consistent with approved procedures?

---

## 13. Security, Privacy, Reliability

- Use role-based access control and secure password/session handling if authentication is implemented.
- Store secrets in environment variables or a secrets manager.
- Validate all external inputs and uploaded files.
- Apply rate limits and authentication to ingestion and action endpoints.
- Maintain immutable or append-only audit events where feasible.
- Back up the database and document restoration steps.
- Minimise personal data; avoid collecting precise resident information unless necessary and authorised.
- Display data source outages and system health.
- Queue and retry ingestion safely; prevent duplicate events with idempotency keys where appropriate.
- Design for low bandwidth, but do not claim offline capability until tested.
- Do not use the prototype as the sole basis for life-safety decisions.

---

## 14. Suggested Repository Structure

```text
hdews/
├── README.md
├── .env.example
├── .gitignore
├── docker-compose.yml
├── docs/
│   ├── research-and-usp.md
│   ├── architecture.md
│   ├── data-dictionary.md
│   ├── safety-and-limitations.md
│   └── evaluation-plan.md
├── frontend/
│   ├── app/
│   ├── components/
│   ├── features/
│   │   ├── overview/
│   │   ├── map/
│   │   ├── sites/
│   │   ├── alerts/
│   │   └── evaluation/
│   ├── lib/
│   └── tests/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── ingestion/
│   │   │   ├── geospatial/
│   │   │   ├── risk_engine/
│   │   │   ├── alerts/
│   │   │   └── llm_explanations/
│   │   └── main.py
│   ├── migrations/
│   └── tests/
├── ml/
│   ├── README.md
│   ├── baselines/
│   ├── experiments/
│   ├── evaluation/
│   └── model_cards/
├── data/
│   ├── README.md
│   ├── sample/
│   └── schemas/
└── scripts/
    ├── seed_demo_data.py
    └── run_demo_scenario.py
```

Do not commit secrets, large restricted datasets, or raw personal data. Include sample data that is safe to redistribute and label synthetic data clearly.

---

## 15. Copy-Paste Prompt for an AI Coding Agent

Use the following as the main implementation prompt for Cursor, Claude Code, Codex, or another coding agent. If the agent has access to an existing repository, instruct it to inspect that repository before changing files.

### MASTER PROMPT

You are a senior full-stack engineer, geospatial systems architect, applied ML engineer, and safety-conscious product designer. Build a working prototype of **HDEWS — Himalayan Disaster Early Warning System** using the specification below.

#### Mission
Build an evidence-first disaster intelligence and human-reviewed early-action platform for a selected Himalayan study area. The initial prototype focuses on rainfall-triggered landslide and flash-flood risk. It must demonstrate a complete end-to-end workflow, not just static screens.

#### Step 0: Inspect before implementation
1. Inspect the current repository, existing code, package manifests, environment files, and README.
2. Identify what is already implemented and what is missing.
3. Preserve working functionality and avoid destructive rewrites.
4. State the implementation plan, major assumptions, and any blockers.
5. Do not claim a feature, dataset, model, API, or integration exists until you verify it.

#### Preferred stack
- Frontend: Next.js, TypeScript, Tailwind CSS, reusable accessible components.
- Map: MapLibre GL JS or Leaflet.
- Charts: Recharts.
- Backend: FastAPI, Python, Pydantic.
- Database: PostgreSQL, with PostGIS if spatial operations need it.
- ML baseline: transparent configurable rules; scikit-learn interface for future model benchmarking.
- Local development: Docker Compose where practical.
If the repository already uses a coherent stack, explain why keeping it is preferable before replacing it.

#### Core features to implement
1. Responsive operations dashboard with data-mode badge and system health.
2. Interactive map with site markers, pilot boundary, layer toggles, legend, and site detail drawer.
3. Monitoring site pages with sensor readings, timestamps, trend charts, provenance, and health status.
4. Risk assessment service for landslide and flash-flood demo scenarios.
5. Evidence cards that show contributing indicators, missing data, freshness, and assessment time.
6. Candidate-alert workflow: create, inspect, acknowledge, assign action, resolve, and audit.
7. Historical event explorer using only available, documented data; otherwise use clearly labelled synthetic sample events.
8. Data-source registry and health view.
9. Evaluation page showing metrics only when supported by real labelled evaluation results.
10. Demo simulator that can vary rainfall, soil moisture, movement, river level, missing values, and sensor outage.
11. Clear distinction between observed, imported, simulated, stale, and model-derived information.
12. Useful loading, empty, error, offline, and permission-denied states.

#### Risk engine requirements
- Implement a documented, configurable baseline first.
- Keep hazard-specific logic separate and unit-tested.
- Do not use an LLM to calculate numerical disaster risk.
- Do not show uncalibrated outputs as real probabilities.
- Return a structured assessment containing hazard type, risk tier, data reliability, contributing factors, missing inputs, assessment timestamp, model/rule version, and provenance references.
- If critical inputs are missing or stale, return an explicit insufficient-data/reliability state rather than silently assuming normal conditions.
- Make clear that all initial thresholds are demo settings, not operational thresholds.

#### LLM explanation assistant
Implement only if a safe and useful provider configuration is available. It must consume structured assessment evidence and generate a short explanation grounded in that evidence. It must not invent measurements, probabilities, warning lead times, or official instructions. If no API key exists, the app must still work and use a deterministic template-based explanation. Never hardcode API keys.

#### Data strategy
- Create source adapters and a canonical observation schema.
- Include a seeded synthetic dataset for local demonstration.
- Include `is_simulated`, `observed_at`, `received_at`, `quality_status`, units, location, and provenance.
- Do not label synthetic readings as live.
- Do not scrape restricted services.
- Do not make external API access mandatory for the basic demo.
- If adding a real data adapter, document source, licence/terms, update cadence, attribution, failure behaviour, and setup instructions.

#### Safety and operational boundaries
- This is a prototype and not a certified public-warning service.
- No automatic evacuation, road closure, emergency declaration, rescue dispatch, or real public alerting.
- Test notifications must be marked DEMO and must not contact real residents.
- Only authorised reviewer roles can change alert status.
- Every alert decision must be recorded in an audit log.
- Separate hazard risk from data reliability.
- Make uncertainty, stale data, and missing data visible.
- Never promise a fixed lead time or accuracy without measured evidence.

#### Design direction
Create a professional emergency-operations interface: high information clarity, strong typographic hierarchy, accessible contrast, restrained colours, clear severity labels, map-first situational awareness, compact data cards, legible charts, and no unnecessary animations. Do not use fake statistics, fabricated agency logos, or claims of government affiliation. The prototype status must be obvious.

#### Engineering quality
- Use typed schemas and validation.
- Add database migrations or reproducible schema creation.
- Provide `.env.example` with placeholders only.
- Add automated tests for risk logic, stale/missing data, alert transitions, and API validation.
- Handle API errors gracefully.
- Add pagination to growing lists.
- Use secure defaults and role checks.
- Keep code modular, readable, and documented.
- Avoid unnecessary microservices and overengineering.
- Include seed/reset scripts for repeatable demonstrations.

#### Deliverables
1. Working source code.
2. A complete root `README.md` with prerequisites, environment setup, run commands, seed-data instructions, tests, architecture, limitations, and troubleshooting.
3. `.env.example`.
4. Docker Compose or clear local run instructions.
5. Sample dataset and a demo scenario.
6. API documentation.
7. Tests and exact test commands.
8. Model/rule card documenting assumptions, intended use, limitations, and evaluation status.
9. Screens or a concise walkthrough describing the end-to-end demonstration.
10. A list of implemented, mocked, and not-yet-implemented features.

#### Acceptance test
A reviewer must be able to start the project, load sample data, open the map, select a site, inspect evidence, change a demo sensor scenario, see the risk assessment update, generate a candidate alert, acknowledge it, assign an action, resolve it, and inspect the audit trail. Missing/stale data must visibly affect reliability. No step may imply that a simulated event is a real emergency.

#### Working method
Implement in small verified phases:
1. Repository audit and architecture plan.
2. Data schemas, seed data, and backend baseline.
3. API and tests.
4. Dashboard and map.
5. Alert workflow and audit log.
6. Simulator and data-quality states.
7. Evaluation and documentation.
8. End-to-end test and final handoff.

After each phase, run the relevant checks and fix failures before proceeding. Do not merely output a plan or mockup: implement the working application in the repository and report what was actually verified. If a dependency, credential, dataset, or integration is unavailable, build a clearly labelled local fallback and document the limitation.

---

## 16. Implementation Roadmap

### Phase 1 — Demonstrable foundation
- Define pilot site(s), schemas, and simulated dataset.
- Build dashboard, map, site detail, and baseline risk engine.
- Add candidate alerts and audit history.
- Demonstrate missing/stale sensor behaviour.

### Phase 2 — Real-data integration
- Select one real precipitation or weather source and one appropriate terrain/satellite-derived layer.
- Record attribution, timestamps, spatial resolution, and refresh behaviour.
- Validate geographic alignment and data quality.
- Keep simulation available for repeatable demos.

### Phase 3 — Model validation
- Obtain a documented event inventory and suitable time-aligned observations.
- Define event labels with domain expertise.
- Create temporal/geographic holdouts and benchmark simple models.
- Publish honest evaluation and model limitations.

### Phase 4 — Field validation
- Work with relevant experts and authorities.
- Calibrate instruments and validate communications.
- Test alert procedures, false alarms, missed events, and user comprehension.
- Do not use the prototype for life-safety decisions until appropriate expert review, validation, and formal authorisation are in place.

---

## 17. Questions to Resolve Before Field Deployment

- Which district, corridor, or specific sites will form the pilot?
- What historical landslide/flood inventory can the team lawfully access?
- Are any physical sensors available, and have they been calibrated?
- Which weather/satellite products can be accessed reliably and legally?
- What is the available budget, timeline, and team expertise?
- Who is the intended operational user, and what approved SOP would govern an alert?
- What connectivity and power assumptions are realistic at the site?
- Who will validate risk outputs and take responsibility for operational decisions?

These questions need not block a clearly labelled software prototype, but they must be answered before making field-performance or safety claims.

---

## 18. Final Recommendation

Build **one excellent, measurable landslide/flash-flood decision-support workflow** before expanding to all Himalayan hazards. The most credible differentiation is the combination of multi-source evidence, explicit data reliability, interpretable risk assessments, and human-reviewed action tracking.

Your prototype should prove:
1. The data sources can be aligned and traced.
2. The risk assessment can explain itself.
3. Missing data is handled safely.
4. A candidate alert can be reviewed and acted on.
5. The system is measurable and honest about its limitations.

That is a stronger innovation story than claiming an all-knowing AI that predicts every disaster.

---

## 19. Source and Claim Discipline

This README combines the original project concept with outside desk research and proposed engineering recommendations. Existing systems and published research are linked above. Architecture, USP, model choices, feature priorities, and prototype workflows are recommendations—not claims that those features have already been built or validated.

Before public presentation:
- Recheck source pages and publication dates.
- Verify current API access, licences, and dataset versions.
- Replace proposed features with implementation evidence only after testing.
- Describe novelty as a hypothesis until a formal prior-art review is completed.
- Have relevant disaster-management and geoscience experts review any safety-critical logic.
