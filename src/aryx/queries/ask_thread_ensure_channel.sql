WITH workspace_row AS (
    SELECT
        id,
        company_id,
        COALESCE(created_by, user_id) AS actor_id
    FROM gg_workspace
    WHERE id = %s::uuid
),
inserted AS (
    INSERT INTO gg_channels (
        id,
        name,
        description,
        channel_tags,
        workspace_id,
        company_id,
        is_active,
        is_public,
        is_archived,
        channel_settings,
        created_by,
        updated_by
    )
    SELECT
        %s::uuid,
        %s,
        %s,
        %s::jsonb,
        workspace_row.id,
        workspace_row.company_id,
        TRUE,
        FALSE,
        FALSE,
        %s::jsonb,
        workspace_row.actor_id,
        workspace_row.actor_id
    FROM workspace_row
    ON CONFLICT (name, workspace_id) DO UPDATE
    SET channel_settings = COALESCE(gg_channels.channel_settings, '{}'::jsonb)
            || EXCLUDED.channel_settings,
        is_archived = FALSE,
        updated_at = NOW()
    RETURNING id::text
)
SELECT id FROM inserted
