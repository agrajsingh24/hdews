-- HDEWS initial schema (SQLite). Timestamps are ISO-8601 UTC strings.
-- A PostgreSQL equivalent lives in ../postgres/001_initial.sql.

CREATE TABLE users (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('admin', 'analyst', 'reviewer', 'viewer')),
    password_hash   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at      TEXT NOT NULL
);

CREATE TABLE sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE TABLE data_sources (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    source_type       TEXT NOT NULL,   -- iot_gateway | simulator | precipitation | terrain | incident_inventory | satellite
    origin            TEXT NOT NULL CHECK (origin IN ('OBSERVED', 'IMPORTED', 'SIMULATED', 'DERIVED')),
    access_mode       TEXT NOT NULL,   -- push_api | internal | file_import | external_api
    description       TEXT NOT NULL,
    attribution       TEXT,
    licence           TEXT,
    url               TEXT,
    update_cadence    TEXT,
    enabled           INTEGER NOT NULL DEFAULT 1,
    health_status     TEXT NOT NULL DEFAULT 'UNKNOWN'
                      CHECK (health_status IN ('HEALTHY', 'DEGRADED', 'STALE', 'UNAVAILABLE', 'NOT_CONFIGURED', 'UNKNOWN')),
    last_success_at   TEXT,
    last_error        TEXT,
    last_error_at     TEXT,
    ingest_key_hash   TEXT
);

CREATE TABLE sites (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    district        TEXT NOT NULL,
    state           TEXT NOT NULL,
    latitude        REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude       REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    elevation_m     REAL,
    hazards         TEXT NOT NULL,     -- JSON array: ["landslide", "flash_flood"]
    description     TEXT NOT NULL,
    location_note   TEXT NOT NULL,
    config          TEXT NOT NULL,     -- JSON: site-specific demo thresholds
    sim_state       TEXT,              -- JSON: active simulated scenario parameters (demo only)
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE sensors (
    id                   TEXT PRIMARY KEY,
    site_id              TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    sensor_type          TEXT NOT NULL CHECK (sensor_type IN ('rain_gauge', 'soil_moisture', 'extensometer', 'river_stage')),
    metric               TEXT NOT NULL,
    unit                 TEXT NOT NULL,
    expected_interval_s  INTEGER NOT NULL CHECK (expected_interval_s > 0),
    source_id            TEXT NOT NULL REFERENCES data_sources(id),
    status               TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'maintenance', 'decommissioned')),
    label                TEXT NOT NULL
);
CREATE INDEX idx_sensors_site ON sensors(site_id);

CREATE TABLE observations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id        TEXT NOT NULL REFERENCES sensors(id) ON DELETE CASCADE,
    site_id          TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    source_id        TEXT NOT NULL REFERENCES data_sources(id),
    metric           TEXT NOT NULL,
    value            REAL,
    unit             TEXT NOT NULL,
    observed_at      TEXT NOT NULL,
    received_at      TEXT NOT NULL,
    quality_status   TEXT NOT NULL CHECK (quality_status IN ('good', 'suspect', 'bad', 'missing')),
    origin           TEXT NOT NULL CHECK (origin IN ('OBSERVED', 'IMPORTED', 'SIMULATED', 'DERIVED')),
    provenance       TEXT NOT NULL,
    scenario_id      TEXT,
    idempotency_key  TEXT UNIQUE,
    UNIQUE (sensor_id, observed_at, origin)
);
CREATE INDEX idx_obs_sensor_time ON observations(sensor_id, observed_at);
CREATE INDEX idx_obs_site_time ON observations(site_id, observed_at);

CREATE TABLE assessments (
    id                      TEXT PRIMARY KEY,
    site_id                 TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    hazard                  TEXT NOT NULL CHECK (hazard IN ('landslide', 'flash_flood')),
    risk_tier               TEXT NOT NULL CHECK (risk_tier IN ('LOW', 'ELEVATED', 'HIGH', 'INSUFFICIENT_DATA')),
    reliability             TEXT NOT NULL CHECK (reliability IN ('GOOD', 'DEGRADED', 'POOR')),
    score                   INTEGER NOT NULL,
    rule_version            TEXT NOT NULL,
    assessed_at             TEXT NOT NULL,
    trigger                 TEXT NOT NULL,
    data_origin             TEXT NOT NULL,   -- SIMULATED | OBSERVED | MIXED | NONE
    payload                 TEXT NOT NULL,   -- JSON: full structured assessment
    previous_assessment_id  TEXT
);
CREATE INDEX idx_assess_site_hazard_time ON assessments(site_id, hazard, assessed_at);

CREATE TABLE alerts (
    id                    TEXT PRIMARY KEY,
    site_id               TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    hazard                TEXT NOT NULL,
    kind                  TEXT NOT NULL CHECK (kind IN ('HAZARD', 'DATA_QUALITY')),
    severity              TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('REVIEW_REQUIRED', 'ACKNOWLEDGED', 'ACTION_ASSIGNED', 'RESOLVED')),
    title                 TEXT NOT NULL,
    data_origin           TEXT NOT NULL,
    dedup_key             TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    first_assessment_id   TEXT NOT NULL REFERENCES assessments(id),
    latest_assessment_id  TEXT NOT NULL REFERENCES assessments(id),
    trigger_count         INTEGER NOT NULL DEFAULT 1,
    acknowledged_by       TEXT REFERENCES users(id),
    acknowledged_at       TEXT,
    resolved_by           TEXT REFERENCES users(id),
    resolved_at           TEXT,
    resolution_category   TEXT CHECK (resolution_category IN ('condition_cleared', 'false_alarm', 'confirmed_event', 'data_issue', 'exercise')),
    resolution_reason     TEXT
);
-- At most one unresolved alert per (site, hazard, kind): prevents duplicate alerts.
CREATE UNIQUE INDEX uq_alert_open_dedup ON alerts(dedup_key) WHERE status <> 'RESOLVED';
CREATE INDEX idx_alerts_status ON alerts(status, created_at);

CREATE TABLE alert_assessments (
    alert_id       TEXT NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    assessment_id  TEXT NOT NULL REFERENCES assessments(id),
    linked_at      TEXT NOT NULL,
    PRIMARY KEY (alert_id, assessment_id)
);

CREATE TABLE alert_actions (
    id           TEXT PRIMARY KEY,
    alert_id     TEXT NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    actor_id     TEXT NOT NULL REFERENCES users(id),
    action_type  TEXT NOT NULL CHECK (action_type IN ('acknowledge', 'field_verification', 'escalation', 'test_notification', 'note', 'resolve')),
    assignee     TEXT,
    notes        TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX idx_alert_actions_alert ON alert_actions(alert_id, created_at);

-- Append-only, hash-chained audit log.
CREATE TABLE audit_log (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL UNIQUE,
    occurred_at  TEXT NOT NULL,
    actor_id     TEXT,
    actor_name   TEXT NOT NULL,
    actor_role   TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    entity_type  TEXT NOT NULL,
    entity_id    TEXT,
    details      TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    hash         TEXT NOT NULL
);
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

CREATE TABLE incidents (
    id                   TEXT PRIMARY KEY,
    hazard               TEXT NOT NULL,
    title                TEXT NOT NULL,
    event_date           TEXT NOT NULL,  -- YYYY-MM-DD (date precision documented separately)
    date_precision       TEXT NOT NULL CHECK (date_precision IN ('day', 'month', 'approximate')),
    location_name        TEXT NOT NULL,
    latitude             REAL NOT NULL,
    longitude            REAL NOT NULL,
    location_precision   TEXT NOT NULL CHECK (location_precision IN ('exact', 'approximate', 'locality')),
    district             TEXT NOT NULL,
    description          TEXT NOT NULL,
    source_name          TEXT NOT NULL,
    source_url           TEXT,
    origin               TEXT NOT NULL CHECK (origin IN ('IMPORTED', 'SYNTHETIC')),
    verification_status  TEXT NOT NULL CHECK (verification_status IN ('VERIFIED_OFFICIAL', 'PUBLIC_REPORT', 'SYNTHETIC')),
    related_site_id      TEXT REFERENCES sites(id),
    notes                TEXT
);

CREATE TABLE scenario_runs (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    site_ids    TEXT NOT NULL,
    params      TEXT NOT NULL,
    applied_by  TEXT NOT NULL REFERENCES users(id),
    applied_at  TEXT NOT NULL
);

CREATE TABLE evaluation_runs (
    id               TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    model_name       TEXT NOT NULL,
    model_version    TEXT NOT NULL,
    dataset_name     TEXT NOT NULL,
    dataset_version  TEXT NOT NULL,
    dataset_kind     TEXT NOT NULL CHECK (dataset_kind IN ('real_labelled')),
    split_strategy   TEXT NOT NULL,
    train_period     TEXT NOT NULL,
    test_period      TEXT NOT NULL,
    regions          TEXT NOT NULL,
    n_test_events    INTEGER NOT NULL,
    n_test_negatives INTEGER NOT NULL,
    metrics          TEXT NOT NULL,
    calibrated       INTEGER NOT NULL DEFAULT 0,
    limitations      TEXT NOT NULL,
    created_by       TEXT NOT NULL
);
