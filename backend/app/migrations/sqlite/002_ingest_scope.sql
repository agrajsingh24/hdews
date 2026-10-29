-- Restrict which sites a push source may write to (HDEWS-007).
-- JSON array of site ids; NULL means the source may not write to any site.
ALTER TABLE data_sources ADD COLUMN ingest_site_scope TEXT;
-- Existing push sources keep the access they had before this migration (every site), so an
-- upgrade never silently stops a working gateway (HDEWS-031). Narrow the scope afterwards with
-- scripts/set_ingest_scope.py.
UPDATE data_sources SET ingest_site_scope = (SELECT json_group_array(id) FROM (SELECT id FROM sites ORDER BY id))
WHERE access_mode = 'push_api';
