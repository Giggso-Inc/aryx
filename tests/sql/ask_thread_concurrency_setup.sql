CREATE TABLE gg_threads (
    id UUID PRIMARY KEY
);

CREATE TABLE gg_messages (
    id UUID PRIMARY KEY,
    content TEXT NOT NULL,
    message_type TEXT NOT NULL,
    thread_id UUID NOT NULL REFERENCES gg_threads(id),
    request_id UUID,
    is_ai_processed BOOLEAN NOT NULL DEFAULT FALSE,
    ai_provider TEXT,
    ai_model TEXT,
    ai_processing_time INTEGER,
    sequence_number INTEGER NOT NULL,
    message_metadata JSONB,
    citations JSONB,
    usage_metrics JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
