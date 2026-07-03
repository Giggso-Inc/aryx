-- 0031 — Add workspace_id to aryx_llm_call so LLM stats are workspace-scoped.
--
-- Previously aryx_llm_call had no workspace column, so the observability
-- dashboard showed global token/latency totals across all workspaces.
-- Existing rows are backfilled to workspace_id=1 (the default workspace).

ALTER TABLE aryx_llm_call
    ADD COLUMN IF NOT EXISTS workspace_id INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_llm_call_workspace_ts
    ON aryx_llm_call (workspace_id, ts DESC);
