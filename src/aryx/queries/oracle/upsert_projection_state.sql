-- Oracle ADB 23ai: upsert projection state.
-- Uses USING DUAL ON (...) so oracledb thin mode parses the bind var.
-- USING (SELECT :x FROM DUAL) is NOT used — thin mode misses binds in subqueries.
-- Named bind (:workspace_id, not positional :1) because it's referenced
-- twice: oracledb thin mode's positional binds count by OCCURRENCE in the
-- SQL text when params arrive as a tuple/sequence (DPY-4009: "2 positional
-- bind values are required but 1 were provided" -- live-confirmed against
-- a real Oracle ADB), unlike named binds passed as a dict, which correctly
-- dedupe by key regardless of how many times :name appears.
-- Params: {"workspace_id": ...}
MERGE INTO aryx_projection_state t
USING DUAL ON (t.workspace_id = :workspace_id)
WHEN MATCHED THEN UPDATE SET t.last_projected_at = CURRENT_TIMESTAMP
WHEN NOT MATCHED THEN INSERT (workspace_id, last_projected_at)
    VALUES (:workspace_id, CURRENT_TIMESTAMP)
