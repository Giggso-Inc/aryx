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
    SET content = EXCLUDED.content,
        is_ai_processed = EXCLUDED.is_ai_processed,
        ai_provider = EXCLUDED.ai_provider,
        ai_model = EXCLUDED.ai_model,
        ai_processing_time = EXCLUDED.ai_processing_time,
        message_metadata = COALESCE(gg_messages.message_metadata, '{}'::jsonb)
            || EXCLUDED.message_metadata,
        citations = EXCLUDED.citations,
        usage_metrics = EXCLUDED.usage_metrics,
        updated_at = NOW()
    RETURNING id::text, sequence_number, (xmax = 0) AS inserted
)
SELECT id, sequence_number, inserted FROM message_row
