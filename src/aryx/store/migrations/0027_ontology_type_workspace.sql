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
-- relies on each statement being idempotent. A check-then-act on conname
-- alone would be wrong twice over: conname is only unique per-table, not
-- database-wide, so a same-named constraint on another table would falsely
-- read as "already exists" here; and two processes racing this migration
-- concurrently could both pass the check before either commits the ADD.
--
-- So: attempt the ADD directly (correct by construction — it targets this
-- exact table, no name lookup involved) and only catch a race against
-- ourselves. UNIQUE also creates a backing index, so the losing side of a
-- concurrent race can fail as either duplicate_object (42710, constraint
-- name collision) or duplicate_table (42P07, the implicit index name
-- collision) depending on timing — both must be caught. And catching either
-- must not silently paper over real drift: if a constraint by this name
-- already exists but isn't UNIQUE (workspace_id, name) — e.g. a prior
-- partial/manual rollout — that is a schema mismatch, not success, so it's
-- raised loudly instead of swallowed.
DO $$
BEGIN
    ALTER TABLE aryx_ontology_type
        ADD CONSTRAINT aryx_ontology_type_ws_name_key
            UNIQUE (workspace_id, name);
EXCEPTION
    WHEN duplicate_object OR duplicate_table THEN
        IF NOT EXISTS (
            SELECT 1
              FROM pg_constraint
             WHERE conname = 'aryx_ontology_type_ws_name_key'
               AND conrelid = 'aryx_ontology_type'::regclass
               AND contype = 'u'
               AND pg_get_constraintdef(oid) = 'UNIQUE (workspace_id, name)'
        ) THEN
            RAISE EXCEPTION
                'aryx_ontology_type_ws_name_key exists on aryx_ontology_type '
                'but is not UNIQUE (workspace_id, name) — schema drift from a '
                'prior partial/manual rollout, needs manual reconciliation';
        END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_ontology_type_ws
    ON aryx_ontology_type (workspace_id);
