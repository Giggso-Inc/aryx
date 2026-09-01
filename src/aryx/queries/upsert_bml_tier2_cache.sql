INSERT INTO aryx_bml_tier2_cache (cache_key, workspace_id, kind, result)
VALUES (%s, %s, %s, %s)
ON CONFLICT (cache_key) DO UPDATE
SET result = EXCLUDED.result, created_at = now()
