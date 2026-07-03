-- Persistent document-discovery store: replaces the in-memory dict in discoveries.py.
-- Discoveries survive container restarts; history is queryable per workspace.
-- No expiry — rows persist indefinitely; UI shows ⚠️ warning after 7 days pending.

CREATE TABLE IF NOT EXISTS aryx_discovery (
    discovery_id    TEXT        PRIMARY KEY,
    workspace_id    INTEGER     NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'pending',
    data_json       TEXT        NOT NULL DEFAULT '{}',
    summary_json    TEXT        NOT NULL DEFAULT '{}',
    file_count      INTEGER     NOT NULL DEFAULT 0,
    confirm_state   TEXT        NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_aryx_discovery_workspace
    ON aryx_discovery (workspace_id, created_at DESC);
