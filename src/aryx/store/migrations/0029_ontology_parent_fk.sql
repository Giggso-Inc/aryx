-- 0029 — Re-create parent_type FK after migration 0027 cascade-dropped it.
--
-- Migration 0017 added:
--   parent_type TEXT REFERENCES aryx_ontology_type(name)
-- Migration 0027 ran:
--   DROP CONSTRAINT aryx_ontology_type_name_key CASCADE
-- CASCADE silently dropped the parent_type FK because it depended on
-- the UNIQUE(name) constraint. The comment in 0027 says "re-created below"
-- but the re-creation was never written. This migration closes the gap.
--
-- The FK now points at (workspace_id, name) so a parent_type can only
-- reference a type in the same workspace (cross-workspace parent hierarchies
-- are not meaningful).

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'aryx_ontology_type_parent_fk'
    ) THEN
        ALTER TABLE aryx_ontology_type
            ADD CONSTRAINT aryx_ontology_type_parent_fk
            FOREIGN KEY (workspace_id, parent_type)
            REFERENCES aryx_ontology_type (workspace_id, name)
            ON UPDATE CASCADE
            ON DELETE SET NULL
            NOT VALID;
    END IF;
END $$;
