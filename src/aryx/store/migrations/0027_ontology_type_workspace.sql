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
--   2. Add UNIQUE(workspace_id, name) — BEFORE dropping the old UNIQUE(name).
--      See the note above step 2 for why the order matters.
--   3. Drop the old UNIQUE(name) (CASCADE also drops parent_type's FK from
--      0017, which depended on it).
--   4. Re-add parent_type's FK, now scoped to (workspace_id, parent_type),
--      so a child can only reference a parent in its own workspace.
--   5. Index workspace_id for the new GET filter.
--
-- apply_migrations() has no applied-migrations ledger — it re-runs every
-- file on every startup, so every statement here must be safe to repeat.
-- Constraints this migration must end up with are verified for real after
-- the whole file runs, in migrate.py's _verify_critical_constraints() — see
-- that function for why enforcement lives there and not in a RAISE inside
-- a DO block here (a RAISE here would just be caught and logged as a
-- warning like any other statement failure, not enforced).

ALTER TABLE aryx_ontology_type
    ADD COLUMN IF NOT EXISTS workspace_id BIGINT NOT NULL DEFAULT 1;

-- Add the new key BEFORE dropping the old one. Every row shares
-- workspace_id=1 at this point (just backfilled above), and the still-live
-- UNIQUE(name) already guarantees no duplicate names exist, so this ADD is
-- guaranteed to succeed against current data — the table is NEVER left
-- without uniqueness protection on name. Dropping first and adding second,
-- as a naive version of this migration would, opens a real window where a
-- concurrent insert can create a duplicate (workspace_id, name) row before
-- the new constraint exists, which would then make the ADD fail outright
-- and leave the table permanently unprotected once the runner swallows
-- that failure.
--
-- Postgres has no ADD CONSTRAINT IF NOT EXISTS. A check-then-act on conname
-- alone would be wrong twice over: conname is only unique per-table, not
-- database-wide, so a same-named constraint on another table would falsely
-- read as "already exists" here; and two processes racing this migration
-- concurrently could both pass the check before either commits the ADD. So:
-- attempt the ADD directly (correct by construction — it targets this exact
-- table, no name lookup involved) and only catch a race against ourselves.
-- UNIQUE also creates a backing index, so the losing side of that race can
-- fail as either duplicate_object (42710, constraint name collision) or
-- duplicate_table (42P07, the implicit index name collision) depending on
-- timing — both are caught here as "someone else already won this race";
-- _verify_critical_constraints() confirms afterward that the result is
-- actually correct rather than just present.
DO $$
BEGIN
    ALTER TABLE aryx_ontology_type
        ADD CONSTRAINT aryx_ontology_type_ws_name_key
            UNIQUE (workspace_id, name);
EXCEPTION
    WHEN duplicate_object OR duplicate_table THEN
        NULL;
END $$;

-- CASCADE also drops the old parent_type -> aryx_ontology_type(name) FK
-- from 0017, which depended on this constraint. Re-added below scoped to
-- (workspace_id, parent_type) — see that ALTER for why.
ALTER TABLE aryx_ontology_type
    DROP CONSTRAINT IF EXISTS aryx_ontology_type_name_key CASCADE;

DROP INDEX IF EXISTS aryx_ontology_type_name_key;

-- parent_type's FK from 0017 referenced bare `name`, which no longer
-- identifies a unique row now that name is only unique per-workspace — a
-- child in workspace 2 could reference a same-named parent that actually
-- belongs to workspace 1. Scope the FK to (workspace_id, parent_type) so a
-- parent must be in the same workspace as its child. NULL parent_type
-- (root types) is still unconstrained, same as before. Same idempotency
-- reasoning as the UNIQUE above: attempt directly, catch only a race
-- against ourselves.
DO $$
BEGIN
    ALTER TABLE aryx_ontology_type
        ADD CONSTRAINT aryx_ontology_type_parent_ws_fkey
            FOREIGN KEY (workspace_id, parent_type)
            REFERENCES aryx_ontology_type (workspace_id, name)
            ON UPDATE CASCADE ON DELETE SET NULL;
EXCEPTION
    WHEN duplicate_object THEN
        NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_ontology_type_ws
    ON aryx_ontology_type (workspace_id);
