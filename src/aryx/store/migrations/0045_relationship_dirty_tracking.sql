-- G8 fix: relationship-only changes were invisible to incremental projection.
-- project_incremental()'s dirty set came only from aryx_entity.updated_at;
-- inserting a NEW relationship between two otherwise-unchanged entities never
-- touched either endpoint's updated_at, so the edge was silently dropped by
-- an incremental (non-full) projection run. This column lets the dirty set
-- be computed from relationship changes directly, independent of entity
-- attribute changes (docs/ingestion/SPARK_PARALLEL_MIGRATION_ANALYSIS_2026-09-23.md
-- Phase 4).

ALTER TABLE aryx_relationship
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_rel_ws_updated ON aryx_relationship (workspace_id, updated_at);
