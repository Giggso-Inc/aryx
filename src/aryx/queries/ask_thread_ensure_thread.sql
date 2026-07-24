INSERT INTO gg_threads (
    id,
    title,
    description,
    channel_id,
    is_active,
    is_archived
)
VALUES (
    %s::uuid,
    %s,
    %s,
    %s::uuid,
    TRUE,
    FALSE
)
ON CONFLICT (id) DO UPDATE
SET title = COALESCE(NULLIF(gg_threads.title, ''), EXCLUDED.title),
    is_archived = FALSE,
    updated_at = NOW()
RETURNING id::text, title
