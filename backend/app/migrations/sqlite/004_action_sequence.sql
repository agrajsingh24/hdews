-- Deterministic ordering of an alert's actions (HDEWS-026): created_at has one-second resolution
-- and ids are random, so actions recorded within the same second could be listed out of order.
ALTER TABLE alert_actions ADD COLUMN seq INTEGER;
UPDATE alert_actions SET seq = (SELECT COUNT(*) FROM alert_actions b WHERE b.alert_id = alert_actions.alert_id AND b.rowid <= alert_actions.rowid);
CREATE UNIQUE INDEX uq_alert_actions_seq ON alert_actions(alert_id, seq);
