-- CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md: per-workspace,
-- uploaded replacement for the hardcoded config_layouts/ folder.
-- One row per (workspace_id, catalog_prefix); a re-upload for the same
-- pair replaces the row (upsert, "last export wins" -- matches the old
-- manifest.json's own semantics). No versioning/history in v1.

CREATE TABLE IF NOT EXISTS aryx_cpq_layout_file (
    layout_id       TEXT        PRIMARY KEY,
    workspace_id    INTEGER     NOT NULL,
    catalog_prefix  TEXT        NOT NULL,
    filename        TEXT        NOT NULL,
    content_clob    TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'active',
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_aryx_cpq_layout_ws_catalog
    ON aryx_cpq_layout_file (workspace_id, catalog_prefix);
