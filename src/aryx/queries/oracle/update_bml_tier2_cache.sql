UPDATE aryx_bml_tier2_cache
SET result = %s, created_at = CURRENT_TIMESTAMP
WHERE cache_key = %s
