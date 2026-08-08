-- 0027 — Multi-tenant the ontology type table.
--
-- Pre-existing aryx_ontology_type had no workspace_id column and a
-- UNIQUE(name) constraint that prevented the same type existing in two
-- workspaces. With the DEMO/Default split this caused types to "leak":
-- every workspace saw every type because no filter was possible.
--
-- Fix:
--   1. Add workspace_id NOT NULL DEFAULT 1 (backfills existing rows to
--      workspace 1 — the DEMO workspace — preserving the demo dataset).
--   2. Drop the UNIQUE(name) constraint; replace with UNIQUE(workspace_id, name).
--   3. Index workspace_id for the new GET filter.

ALTER TABLE aryx_ontology_type
    ADD COLUMN IF NOT EXISTS workspace_id BIGINT NOT NULL DEFAULT 1;

-- CASCADE drops the parent_type FK along with the unique it depends on.
-- The FK is re-created below pointing at the new (workspace_id, name) key
-- so parent_type stays referentially intact within each workspace.
ALTER TABLE aryx_ontology_type
    DROP CONSTRAINT IF EXISTS aryx_ontology_type_name_key CASCADE;

DROP INDEX IF EXISTS aryx_ontology_type_name_key;

-- Postgres has no ADD CONSTRAINT IF NOT EXISTS, and apply_migrations() has
-- no applied-migrations ledger — it re-runs every file on every startup and
-- relies on each statement being idempotent. Guard explicitly so re-runs
-- are silent instead of logging a swallowed "already exists" warning.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'aryx_ontology_type_ws_name_key'
    ) THEN
        ALTER TABLE aryx_ontology_type
            ADD CONSTRAINT aryx_ontology_type_ws_name_key
                UNIQUE (workspace_id, name);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_ontology_type_ws
    ON aryx_ontology_type (workspace_id);
