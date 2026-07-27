-- Oracle ADB 23ai: upsert the hidden Ask channel via MERGE.
-- No RETURNING here -- Oracle MERGE's RETURNING support is unreliable across
-- both the MATCHED/NOT MATCHED branches; the caller does a follow-up SELECT
-- (ask_thread_select_channel_id.sql) instead of relying on it, matching the
-- 2-round-trip pattern already used for provenance batches elsewhere.
-- Each positional bind (:1..:6) appears exactly once -- oracledb's thin
-- client does not dedupe positional binds by number the way named binds
-- dedupe by name (see upsert_ontology_type.sql), so a nested subquery is
-- used to compute req_workspace_id once and join on it, rather than
-- referencing :1 a second time in a WHERE/JOIN clause.
MERGE INTO gg_channels t
USING (
    SELECT
        inner_src.req_workspace_id,
        inner_src.req_id,
        inner_src.req_name,
        inner_src.req_description,
        inner_src.req_tags,
        inner_src.req_settings,
        w.company_id AS company_id,
        COALESCE(w.created_by, w.user_id) AS actor_id
    FROM (
        SELECT
            :1 AS req_workspace_id,
            :2 AS req_id,
            :3 AS req_name,
            :4 AS req_description,
            :5 AS req_tags,
            :6 AS req_settings
        FROM dual
    ) inner_src
    JOIN gg_workspace w ON w.id = inner_src.req_workspace_id
) src
ON (t.name = src.req_name AND t.workspace_id = src.req_workspace_id)
WHEN MATCHED THEN
    UPDATE SET
        t.channel_settings = JSON_MERGEPATCH(NVL(t.channel_settings, '{}'), src.req_settings),
        t.is_archived = 0,
        t.updated_at = CURRENT_TIMESTAMP
WHEN NOT MATCHED THEN
    -- channel_type/message_count/ai_enabled/created_at/updated_at are
    -- NOT NULL with no DB-level default -- shay_backend/app/models/channel.py
    -- applies these at the SQLAlchemy ORM layer only (default=1/0/True/
    -- current_timestamp), which a raw INSERT never sees. Values below match
    -- that model's declared defaults exactly (confirmed by reading it, not
    -- guessed).
    INSERT (
        id, name, description, channel_tags, workspace_id, company_id,
        is_active, is_public, is_archived, channel_type, message_count,
        ai_enabled, channel_settings, created_by, updated_by,
        created_at, updated_at
    )
    VALUES (
        src.req_id, src.req_name, src.req_description, src.req_tags,
        src.req_workspace_id, src.company_id,
        1, 0, 0, 1, 0,
        1, src.req_settings, src.actor_id, src.actor_id,
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    )
