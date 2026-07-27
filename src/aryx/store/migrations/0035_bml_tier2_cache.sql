-- Durable Tier-2 BML result cache (Amendment 18 option 4, docs/
-- CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md). BmlEvaluator's existing
-- _SHARED_SCRIPT_CACHE is process-local, in-memory only — lost on every
-- restart and never shared across worker processes. This table survives
-- both, for the SAME (workspace, catalog, script, variable-state) key
-- semantics already used in-memory, so a Tier-2 LLM answer is paid for once
-- per real state, not once per process lifetime.

CREATE TABLE IF NOT EXISTS aryx_bml_tier2_cache (
    cache_key    VARCHAR(64) PRIMARY KEY,
    workspace_id BIGINT NOT NULL,
    kind         TEXT NOT NULL,
    result       JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bml_tier2_cache_ws ON aryx_bml_tier2_cache (workspace_id);
