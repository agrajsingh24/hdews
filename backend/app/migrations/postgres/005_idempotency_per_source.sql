-- Idempotency keys are namespaced by source (HDEWS-032): previously they were unique across all
-- sources, so two gateways using the same key scheme silently discarded each other's readings.
-- Stored form: '<source_id>:<client key>'.
UPDATE observations SET idempotency_key = source_id || ':' || idempotency_key
WHERE idempotency_key IS NOT NULL AND left(idempotency_key, length(source_id) + 1) <> source_id || ':';
