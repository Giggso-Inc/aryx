-- 0039 -- Case-insensitive ontology_type lookup index for aryx_entity.
--
-- aryx.cpq.rdb.fetch_entities_by_exact_type() (backing the Data Table
-- resolver, see aryx.cpq.data_table_resolver) filters on
-- lower(ontology_type) = lower($2). The existing idx_entity_ws_type index
-- from 0009_workspaces.sql is on the plain (workspace_id, ontology_type)
-- columns and cannot serve a lower()-wrapped predicate, so every call fell
-- back to a full sequential scan of the workspace's aryx_entity rows --
-- confirmed live via pg_stat_activity on a 453K-row workspace: repeated
-- 3-8s scans, several stacked concurrently, once per ingested ontology_type
-- per governed attribute resolved in a single /ask turn.

CREATE INDEX IF NOT EXISTS idx_entity_ws_type_lower
    ON aryx_entity (workspace_id, lower(ontology_type));
