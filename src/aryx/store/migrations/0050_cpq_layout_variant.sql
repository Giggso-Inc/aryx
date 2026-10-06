-- Layout variants: several layout exports per (workspace_id, catalog_prefix),
-- told apart by `variant` (the export's own top-level variableName).
-- NOT NULL with a sentinel default (never NULL / empty string: Oracle treats
-- '' as NULL and a NULL in a unique key never conflicts). Existing rows get
-- the sentinel, so single-layout catalogs keep working unchanged.
-- The sentinel literal below must equal DEFAULT_LAYOUT_VARIANT in
-- aryx/cpq/layout_source.py.

ALTER TABLE aryx_cpq_layout_file ADD COLUMN IF NOT EXISTS variant TEXT NOT NULL DEFAULT 'default';

-- 0046 re-runs on every boot (no tracking table), and its IF NOT EXISTS
-- index keeps the same name, so replace that index in place only while it
-- still lacks the variant column.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_indexes
             WHERE indexname = 'idx_aryx_cpq_layout_ws_catalog'
               AND indexdef NOT LIKE '%variant%') THEN
    DROP INDEX idx_aryx_cpq_layout_ws_catalog;
  END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_aryx_cpq_layout_ws_catalog
    ON aryx_cpq_layout_file (workspace_id, catalog_prefix, variant);
