INSERT INTO aryx_discovery (discovery_id, workspace_id, data, updated_at)
VALUES (%s, %s, %s, now())
ON CONFLICT (discovery_id)
DO UPDATE SET workspace_id = EXCLUDED.workspace_id,
              data = EXCLUDED.data,
              updated_at = now()
