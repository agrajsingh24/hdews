-- Restrict which sites a push source may write to (HDEWS-007).
-- JSON array of site ids; NULL means the source may not write to any site.
ALTER TABLE data_sources ADD COLUMN ingest_site_scope TEXT;
-- Existing push sources keep the access they had before this migration (every site) (HDEWS-031).
UPDATE data_sources SET ingest_site_scope = (SELECT COALESCE(json_agg(id ORDER BY id), '[]'::json)::text FROM sites)
WHERE access_mode = 'push_api';
