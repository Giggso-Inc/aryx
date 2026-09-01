UPDATE gg_channels
SET message_count = message_count + 1,
    last_message_at = NOW(),
    updated_at = NOW()
WHERE id = %s::uuid
