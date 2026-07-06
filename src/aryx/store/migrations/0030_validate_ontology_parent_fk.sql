-- 0030 — Validate the parent_type FK added as NOT VALID in migration 0029.
--
-- Migration 0029 used NOT VALID to avoid a full table scan on deploy.
-- Rows written after 0029 are fully constrained. This migration validates
-- existing (historical) rows so the constraint applies to the entire table.
--
-- VALIDATE CONSTRAINT acquires a ShareUpdateExclusiveLock (not AccessExclusive),
-- so it does not block concurrent reads or writes. Safe to run in production.
--
-- Run this migration during a low-traffic window or as a background step.
-- If validation fails, a row exists with parent_type pointing to a type in
-- a different workspace — investigate with:
--   SELECT workspace_id, name, parent_type FROM aryx_ontology_type
--   WHERE parent_type IS NOT NULL
--     AND NOT EXISTS (
--       SELECT 1 FROM aryx_ontology_type p
--       WHERE p.workspace_id = aryx_ontology_type.workspace_id
--         AND p.name = aryx_ontology_type.parent_type
--     );

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'aryx_ontology_type_parent_fk'
          AND NOT convalidated
    ) THEN
        ALTER TABLE aryx_ontology_type
            VALIDATE CONSTRAINT aryx_ontology_type_parent_fk;
    END IF;
END $$;
