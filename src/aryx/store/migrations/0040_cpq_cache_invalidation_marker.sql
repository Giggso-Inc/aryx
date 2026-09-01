-- docs/CPQ_ASK_THREADS_MESSAGE_CONCURRENCY_DELAY report, Section 12 --
-- cross-process invalidation for the CPQ rule/table caches. Under a
-- single api worker process, clearing an in-process cache dict on
-- ingest-confirm was sufficient (docs/CPQ_TURN_LATENCY_FIX_CORRECTNESS_
-- RISK_2026_08_19.md). Multi-worker (PR #287, P1) reopens that risk: an
-- ingest handled by one worker never reaches another worker's copy of
-- the same cache. This single-row table is the shared "last changed"
-- clock every worker polls (short local TTL, not per-request) to notice
-- a re-ingest it didn't itself handle and clear its own stale entries.
CREATE TABLE IF NOT EXISTS cpq_cache_invalidation_marker (
    id             INT PRIMARY KEY DEFAULT 1,
    invalidated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_job_id    TEXT,
    CONSTRAINT cpq_cache_invalidation_marker_single_row CHECK (id = 1)
);

INSERT INTO cpq_cache_invalidation_marker (id, invalidated_at)
VALUES (1, now())
ON CONFLICT (id) DO NOTHING;
