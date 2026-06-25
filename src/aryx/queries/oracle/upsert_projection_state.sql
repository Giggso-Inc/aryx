-- Oracle ADB 23ai: upsert projection state.
-- Replaces: INSERT ... ON CONFLICT (workspace_id) DO UPDATE SET last_projected_at = now()
MERGE INTO aryx_projection_state t
USING (SELECT :1 AS workspace_id FROM DUAL) s
ON (t.workspace_id = s.workspace_id)
WHEN MATCHED THEN UPDATE SET t.last_projected_at = CURRENT_TIMESTAMP
WHEN NOT MATCHED THEN INSERT (workspace_id, last_projected_at)
    VALUES (s.workspace_id, CURRENT_TIMESTAMP)
