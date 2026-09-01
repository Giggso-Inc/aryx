-- Oracle ADB 23ai: plain INSERT, no ON CONFLICT (Oracle has no direct
-- equivalent, and translating DO UPDATE generically would silently
-- degrade to insert-or-ignore -- see oracle_pool.py's _translate_sql).
-- Safe here specifically because BmlEvaluator._durable_put() (the only
-- caller) already checks for an existing row via
-- select_bml_tier2_cache_exists.sql before ever reaching this query, and
-- takes the update_bml_tier2_cache.sql path instead when one exists --
-- this INSERT only runs on a guaranteed-fresh cache_key.
INSERT INTO aryx_bml_tier2_cache (cache_key, workspace_id, kind, result)
VALUES (%s, %s, %s, %s)
