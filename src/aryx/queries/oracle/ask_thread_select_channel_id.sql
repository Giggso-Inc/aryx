-- Oracle ADB 23ai: fetch the channel id after ask_thread_ensure_channel's
-- MERGE (which has no reliable RETURNING). Params: :1=workspace_id :2=name
SELECT id
FROM gg_channels
WHERE workspace_id = :1 AND name = :2
FETCH FIRST 1 ROWS ONLY
