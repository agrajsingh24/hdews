# HDEWS API

Base path `/api`. JSON in and out. Authenticate with `POST /api/auth/login`, then send `Authorization: Bearer <token>`.

**Errors** always have the form `{"error": {"code": "...", "message": "...", "details": ...}}`.
Codes: `unauthenticated` (401), `invalid_credentials` (401), `forbidden` (403, details list required roles), `not_found` (404), `invalid_transition` (409), `validation_error` (422, details list `field`/`message`), `invalid_json` (400), `rate_limited` (429), `internal_error` (500).

**Pagination**: `limit` (1–200) and `offset`; list responses are `{items, total, limit, offset, has_more}`.

**Roles → permissions**: viewer `read`; analyst `read, run_assessment, run_scenario`; reviewer `read, run_assessment, alert_review`; admin all (adds `manage_config`, `manage_sources`).

| Method & path | Permission | Purpose |
|---|---|---|
| `GET /health` | public | Liveness, DB dialect, last observation time |
| `GET /meta` | public | Environment, rule version, safety notice, demo login hint (not in production) |
| `POST /auth/login` | public (10/min/IP) | `{username, password}` → `{token, expires_at, user}` |
| `POST /auth/logout` | token | Invalidates the session |
| `GET /auth/me` | token | User and permission list |
| `GET /overview` | read | Dashboard aggregate: latest tiers per site/hazard, open alerts, sensor states, origin counts, hourly rain, tier changes |
| `GET /map/layers` | read | Pilot box, sites with latest assessments, demo hazard zones, schematic rivers, places, incidents, layer metadata |
| `GET /rules` | read | Defaults, indicators/points, tier logic, playbook |
| `GET /sites` | read | Sites with sensor states and latest assessments |
| `GET /sites/{id}` | read | Site, effective config, sensors with health, indicators, latest assessments, alerts, incidents |
| `GET /sites/{id}/observations?hours=1..168` | read | Per-sensor series: `{id, t (observed), r (received), v, q, o (origin), src}` |
| `POST /sites/{id}/assess` | run_assessment | Re-run the assessment now |
| `PUT /sites/{id}/config` | manage_config | `{overrides}` validated site thresholds; audited; re-assesses |
| `GET /assessments?site_id&hazard&risk_tier&reliability` | read | Paginated |
| `GET /assessments/{id}` | read | Full structured assessment + evidence observations |
| `GET /assessments/{id}/explanation` | read | `{method: template|llm, text, disclaimer, llm_note}` |
| `GET /alerts?status=open|resolved|all|<STATUS>&kind&site_id&hazard` | read | Paginated, unreviewed first |
| `GET /alerts/{id}` | read | Alert, triggering/current assessment, evidence, actions, audit history |
| `POST /alerts/{id}/acknowledge` | alert_review | `{notes?}`; only from REVIEW_REQUIRED |
| `POST /alerts/{id}/actions` | alert_review | `{action_type: field_verification|escalation|test_notification|note, notes, assignee}`; assigning types need an acknowledged alert and an assignee |
| `POST /alerts/{id}/resolve` | alert_review | `{category: condition_cleared|false_alarm|confirmed_event|data_issue|exercise, reason}`; requires acknowledgement |
| `GET /incidents?q&hazard&origin&verification_status&from&to` | read | Paginated |
| `GET /incidents/{id}` | read | Incident, nearest sites, associated observations (if any) |
| `GET /data-sources` | read | Registry with derived health |
| `GET /audit-log?entity_type&entity_id&event_type&event_prefix&actor_id` | read | Paginated, newest first |
| `GET /audit-log/verify` | read | Recomputes the hash chain |
| `GET /evaluation` | read | `NOT_EVALUATED` with requirements, or recorded runs |
| `GET /demo/presets` | read; demo only | Presets, parameters, sites |
| `POST /demo/scenario` | run_scenario; demo only | `{site_ids, preset?, overrides?, name?}` → generated counts + new assessments |
| `POST /ingestion/{source_id}` | `X-HDEWS-Ingest-Key` (120/min/IP) | `{readings: [{sensor_id, observed_at, value, quality_status?, idempotency_key?}]}` (≤ 500) → `{accepted, duplicates, rejected[], sites}`; 202 if any accepted |

Demo endpoints return 404 when `HDEWS_ENV=production`.

### Example
```bash
TOKEN=$(curl -s localhost:8000/api/auth/login -H 'content-type: application/json' \
  -d '{"username":"analyst","password":"hdews-demo"}' | python -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -X POST localhost:8000/api/demo/scenario -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"site_ids":["SNP-05"],"preset":"rapid_river_rise"}'
```
