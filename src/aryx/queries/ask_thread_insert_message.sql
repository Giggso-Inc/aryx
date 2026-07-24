WITH locked_thread AS (
    SELECT id
    FROM gg_threads
    WHERE id = %s::uuid
    FOR UPDATE
),
next_sequence AS (
    SELECT COALESCE(MAX(sequence_number), 0) + 1 AS value
    FROM gg_messages
    WHERE thread_id = (SELECT id FROM locked_thread)
),
message_row AS (
    INSERT INTO gg_messages (
        id,
        content,
        message_type,
        thread_id,
        request_id,
        is_ai_processed,
        ai_provider,
        ai_model,
        ai_processing_time,
        sequence_number,
        message_metadata,
        citations,
        usage_metrics
    )
    SELECT
        %s::uuid,
        %s,
        %s,
        %s::uuid,
        %s::uuid,
        %s,
        %s,
        %s,
        %s,
        next_sequence.value,
        %s::jsonb,
        %s::jsonb,
        %s::jsonb
    FROM next_sequence
    ON CONFLICT (thread_id, request_id, message_type) WHERE request_id IS NOT NULL
    DO UPDATE
    SET content = CASE
            WHEN gg_messages.message_type = 'user' THEN gg_messages.content
            ELSE EXCLUDED.content
        END,
        is_ai_processed = CASE
            WHEN gg_messages.message_type = 'user' THEN gg_messages.is_ai_processed
            ELSE EXCLUDED.is_ai_processed
        END,
        ai_provider = CASE
            WHEN gg_messages.message_type = 'user' THEN gg_messages.ai_provider
            ELSE EXCLUDED.ai_provider
        END,
        ai_model = CASE
            WHEN gg_messages.message_type = 'user' THEN gg_messages.ai_model
            ELSE EXCLUDED.ai_model
        END,
        ai_processing_time = CASE
            WHEN gg_messages.message_type = 'user' THEN gg_messages.ai_processing_time
            ELSE EXCLUDED.ai_processing_time
        END,
        message_metadata = CASE
            WHEN gg_messages.message_type = 'user' THEN
                COALESCE(gg_messages.message_metadata, '{}'::jsonb)
                || EXCLUDED.message_metadata
            ELSE COALESCE(gg_messages.message_metadata, '{}'::jsonb)
                || EXCLUDED.message_metadata
        END,
        citations = CASE
            WHEN gg_messages.message_type = 'user' THEN gg_messages.citations
            ELSE EXCLUDED.citations
        END,
        usage_metrics = CASE
            WHEN gg_messages.message_type = 'user' THEN gg_messages.usage_metrics
            ELSE EXCLUDED.usage_metrics
        END,
        updated_at = NOW()
    WHERE gg_messages.message_type <> 'user'
       OR (
            gg_messages.content = EXCLUDED.content
            AND (
                gg_messages.message_metadata->>'request_status' = 'failed'
                OR (
                    gg_messages.message_metadata->>'request_status' IS NULL
                    AND EXISTS (
                        SELECT 1
                        FROM gg_messages AS failed_response
                        WHERE failed_response.thread_id = gg_messages.thread_id
                          AND failed_response.request_id = gg_messages.request_id
                          AND failed_response.message_type = 'system'
                          AND NULLIF(
                              BTRIM(COALESCE(failed_response.message_metadata->>'error', '')),
                              ''
                          ) IS NOT NULL
                    )
                )
                OR (
                    gg_messages.message_metadata->>'request_status' = 'in_progress'
                    AND gg_messages.updated_at < NOW() - INTERVAL '20 minutes'
                )
            )
        )
    RETURNING id::text, sequence_number, (xmax = 0) AS inserted, content
)
SELECT id, sequence_number, inserted, content FROM message_row
