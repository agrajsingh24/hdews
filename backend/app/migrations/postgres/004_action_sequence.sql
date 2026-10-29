-- Deterministic ordering of an alert's actions (HDEWS-026). See ../sqlite/004_action_sequence.sql.
ALTER TABLE alert_actions ADD COLUMN seq INTEGER;
UPDATE alert_actions a SET seq = r.n FROM (
  SELECT id, ROW_NUMBER() OVER (PARTITION BY alert_id ORDER BY created_at, id) AS n FROM alert_actions) r
WHERE a.id = r.id;
CREATE UNIQUE INDEX uq_alert_actions_seq ON alert_actions(alert_id, seq);
