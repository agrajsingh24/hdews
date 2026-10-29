-- Indexes for queries that otherwise scan tables which grow without bound (HDEWS-024):
-- the overview's recent tier changes (audit_log by event type) and the unfiltered assessment list.
CREATE INDEX idx_audit_event_type_seq ON audit_log(event_type, seq);
CREATE INDEX idx_assess_time ON assessments(assessed_at);
