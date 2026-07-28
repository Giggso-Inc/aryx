-- Durable store for document-discovery results (read step) awaiting confirm.
--
-- Real incident (Raven review, PR #120): the read job's progress callback
-- genuinely flushes a growing partial snapshot on every N chunks, but it
-- flushed into aryx.discoveries' in-process dict — a crash or restart
-- partway through a long (1000+ page) document wiped every mention
-- extracted so far, with the job's own stage/pct (durable in aryx_job)
-- misleadingly still showing accurate-looking progress for data that no
-- longer existed. Storing the same payload in Postgres instead survives a
-- process restart the same way aryx_job already does.
CREATE TABLE IF NOT EXISTS aryx_discovery (
    discovery_id TEXT PRIMARY KEY,
    workspace_id INTEGER NOT NULL,
    data         JSONB NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_discovery_workspace ON aryx_discovery (workspace_id);
