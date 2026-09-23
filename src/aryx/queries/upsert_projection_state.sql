INSERT INTO aryx_projection_state (workspace_id, last_projected_at)
VALUES (%(workspace_id)s, now())
ON CONFLICT (workspace_id)
DO UPDATE SET last_projected_at = now()
