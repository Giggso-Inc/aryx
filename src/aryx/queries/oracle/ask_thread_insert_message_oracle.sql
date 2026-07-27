-- Oracle ADB 23ai: plain insert of a new message row. The caller has already
-- confirmed no existing row for this (thread_id, request_id, message_type)
-- via ask_thread_select_existing_message.sql, under the thread's row lock,
-- so there is no conflict to handle here (unlike the Postgres upsert).
-- Params in order: :1=id :2=content :3=message_type :4=thread_id :5=request_id
-- :6=is_ai_processed :7=ai_provider :8=ai_model :9=ai_processing_time
-- :10=sequence_number :11=message_metadata :12=citations :13=usage_metrics
-- is_visible/is_pinned/created_at/updated_at are NOT NULL with no DB-level
-- default -- shay_backend/app/models/message.py's Message class applies
-- these at the SQLAlchemy ORM layer only (default=True/False/
-- current_timestamp), which a raw INSERT never sees.
INSERT INTO gg_messages (
    id, content, message_type, thread_id, query_id, is_ai_processed,
    ai_provider, ai_model, ai_processing_time, sequence_number,
    message_metadata, citations, usage_metrics,
    is_visible, is_pinned, created_at, updated_at
) VALUES (
    :1, :2, :3, :4, :5, :6, :7, :8, :9, :10, :11, :12, :13,
    1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
)
