-- migration: required
-- Sales CPQ MCP authorization, actor-owned chats, and durable MSI workflow state.

ALTER TABLE aryx_mcp_token
    ADD COLUMN IF NOT EXISTS purpose TEXT NOT NULL DEFAULT 'general';
ALTER TABLE aryx_mcp_token
    ADD COLUMN IF NOT EXISTS allowed_tools TEXT NOT NULL DEFAULT '';
ALTER TABLE aryx_mcp_token
    ADD COLUMN IF NOT EXISTS workspace_id BIGINT;
ALTER TABLE aryx_mcp_token
    ADD COLUMN IF NOT EXISTS shay_workspace_id TEXT;
ALTER TABLE aryx_mcp_token
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS aryx_sales_chat_thread (
    thread_id UUID PRIMARY KEY,
    actor_id TEXT NOT NULL,
    workspace_id BIGINT NOT NULL REFERENCES aryx_workspace(id),
    shay_workspace_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sales_chat_actor
    ON aryx_sales_chat_thread (actor_id, workspace_id, shay_workspace_id);

CREATE TABLE IF NOT EXISTS aryx_sales_msi_workflow (
    workflow_id UUID PRIMARY KEY,
    confirmation_id UUID NOT NULL UNIQUE,
    actor_id TEXT NOT NULL,
    thread_id UUID NOT NULL,
    status TEXT NOT NULL,
    current_step TEXT NOT NULL DEFAULT '',
    request_payload JSONB NOT NULL,
    identifiers JSONB NOT NULL DEFAULT '{}'::jsonb,
    steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_message TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sales_msi_actor_updated
    ON aryx_sales_msi_workflow (actor_id, updated_at DESC);
