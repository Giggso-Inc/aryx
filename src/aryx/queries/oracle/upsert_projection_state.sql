-- Oracle ADB 23ai: upsert projection state.
-- Uses USING DUAL ON (...) so oracledb thin mode parses :1 bind var.
-- USING (SELECT :1 FROM DUAL) is NOT used — thin mode misses binds in subqueries.
-- Params: :1=workspace_id
MERGE INTO aryx_projection_state t
USING DUAL ON (t.workspace_id = :1)
WHEN MATCHED THEN UPDATE SET t.last_projected_at = CURRENT_TIMESTAMP
WHEN NOT MATCHED THEN INSERT (workspace_id, last_projected_at)
    VALUES (:1, CURRENT_TIMESTAMP)
