-- 0032 — FK from aryx_llm_call.workspace_id to aryx_workspace.id.
--
-- Migration 0031 added the workspace_id column with DEFAULT 1 but left it
-- as a bare INTEGER. This migration adds a FOREIGN KEY with ON DELETE CASCADE
-- so rows are automatically removed when a workspace is deleted, preventing
-- orphaned LLM call rows.
--
-- NOT VALID skips the full-table scan on deploy (safe for large tables).
-- Run 0033 or a manual VALIDATE CONSTRAINT during a low-traffic window to
-- enforce the constraint on pre-existing rows.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'aryx_llm_call_workspace_fk'
    ) THEN
        ALTER TABLE aryx_llm_call
            ADD CONSTRAINT aryx_llm_call_workspace_fk
            FOREIGN KEY (workspace_id)
            REFERENCES aryx_workspace (id)
            ON DELETE CASCADE
            NOT VALID;
    END IF;
END $$;
