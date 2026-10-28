# Architecture

HDEWS is a modular monolith: one Python process serves the REST API, the compiled frontend and a background loop.

```
                     ┌─────────────────────────── backend (Starlette) ───────────────────────────┐
 Field gateway ──POST /api/ingestion/{src}──► ingestion.py ─┐                                     │
 (X-HDEWS-Ingest-Key, idempotency keys)                      │                                     │
 Simulator UI ───POST /api/demo/scenario────► simulator.py ──┼──► observations table               │
 Background loop (60 s) ──── simulator.tick ─────────────────┘        │                            │
                                                                       ▼                            │
                              assessments.py: site_features() ──► risk_engine (pure functions)      │
                                                                       │  tier, reliability,        │
                                                                       │  factors, evidence ids     │
                                                                       ▼                            │
                              assessments table ──► alerts.py: dedup / create / lifecycle           │
                                                                       │                            │
                                         audit.py (hash chain, append-only triggers) ◄─────────────┘
                                                                       │
                     REST JSON (RBAC, pagination, structured errors) ──► TypeScript SPA
```

## Module map

| Path | Responsibility |
|---|---|
| `app/main.py` | App factory, routes, middleware (security headers, request log), error handlers, background loop |
| `app/config.py` | Settings from environment / `.env` |
| `app/db.py` | SQLite/PostgreSQL access, transactions, migrations runner |
| `app/security.py` | scrypt password hashes, session tokens (hash-stored), role → permission map |
| `app/api/*` | Thin HTTP handlers: validation (Pydantic), permission checks, pagination |
| `services/risk_engine/` | Feature extraction, hazard rules, engine, playbook, config — no I/O |
| `services/assessments.py` | Loads observations, runs engine, persists, triggers alerts |
| `services/alerts.py` | Candidate alert creation, deduplication, state machine |
| `services/simulator.py` | Demo scenarios and continuing simulated telemetry |
| `services/ingestion.py` | Authenticated, idempotent ingestion with range checks |
| `services/audit.py` | Hash-chained audit events and chain verification |
| `services/explanations.py` | Template explanations; optional LLM with grounding check |
| `frontend/src/` | SPA: `main.ts` router/shell, `pages/*`, `map.ts`, `charts.ts`, `dom.ts` |

## Key design decisions

* **Risk and reliability are independent outputs** of every assessment and appear together in a single UI component.
* **Unknown is not safe.** Missing critical data yields `INSUFFICIENT_DATA` or a flagged lower bound.
* **Deduplication** is enforced twice: in service logic and by a partial unique index (`alerts(dedup_key) WHERE status <> 'RESOLVED'`).
* **Audit integrity**: append-only triggers + SHA-256 hash chain; `GET /api/audit-log/verify` recomputes the chain.
* **Provenance**: every observation carries `origin`, `source_id`, `observed_at`, `received_at`, `quality_status`, `provenance`; assessments carry evidence observation ids and a summarised `data_origin`.
* **Demo isolation**: simulator endpoints return 404 when `HDEWS_ENV=production`; applying a scenario deletes only `SIMULATED` observations of the chosen sites.
* **Time**: stored as ISO-8601 UTC strings; the UI renders IST with the UTC value in a tooltip.

## Database
Schema: `backend/app/migrations/{sqlite,postgres}/001_initial.sql`. The PostgreSQL file was applied to PostgreSQL 16 with `psql` (tables and append-only trigger verified). The Python PostgreSQL path (`psycopg`) is implemented but was not exercised because the package could not be installed offline. Coordinates are stored as numeric latitude/longitude; PostGIS is not required at this scale.

## Background loop
Every 60 s (when `ENABLE_BACKGROUND_REASSESSMENT=true`): continue simulated telemetry for sites with an active scenario, then re-assess all sites if new data arrived or `REASSESSMENT_INTERVAL_S` elapsed. Stale data therefore surfaces automatically if a feed stops.

## Scaling notes
Single-process, single-node by design (in-memory rate limiter, SQLite). For multi-node: PostgreSQL, a shared rate limiter, and a separate scheduler process for the background loop.
