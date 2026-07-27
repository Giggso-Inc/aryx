-- Oracle ADB 23ai: overwrite a message row. Caller has already decided (in
-- Python, mirroring the Postgres conditional-overwrite WHERE clause) that
-- this update should happen -- see AryxAskThreadStore._insert_message_oracle.
-- Params: :1=content :2=is_ai_processed :3=ai_provider :4=ai_model
-- :5=ai_processing_time :6=message_metadata :7=citations :8=usage_metrics
-- :9=id
UPDATE gg_messages
SET content = :1,
    is_ai_processed = :2,
    ai_provider = :3,
    ai_model = :4,
    ai_processing_time = :5,
    message_metadata = JSON_MERGEPATCH(NVL(message_metadata, '{}'), :6),
    citations = :7,
    usage_metrics = :8,
    updated_at = CURRENT_TIMESTAMP
WHERE id = :9
