-- Durable storage for CPQ rule-execution traces (docs/
-- CPQ_RULE_EXPORT_AND_TRACE_TDD_PLAN.md).
--
-- One session (run_id) accumulates one row per fired rule across every
-- ask-turn until the configuration is confirmed (session.complete becomes
-- True — see aryx.cpq.rule_trace's docstring for why "approved" was
-- rejected as the confirm signal: it is dead legacy code, never actually
-- set; ask_api.py's real confirm handler sets session.complete = True and
-- session.status = "post_approval" together at BOM-payload generation).
--
-- Each fired rule is written as its OWN small row in real time, not
-- buffered and flushed as one blob at seal-time — the opposite failure
-- shape of the aryx_discovery incident (migration 0036): that crash came
-- from one oversized write; many small rows never approach any single-
-- write size ceiling, and a mid-session crash still leaves the partial
-- trace durably saved instead of losing it entirely.
CREATE TABLE IF NOT EXISTS aryx_rule_trace_session (
    run_id         TEXT PRIMARY KEY,
    workspace_id   INTEGER NOT NULL,
    catalog_prefix TEXT NOT NULL DEFAULT '',
    file_key       TEXT NOT NULL,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    sealed_at      TIMESTAMPTZ,
    status         TEXT NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open', 'post_approval', 'orphaned_timeout'))
);

CREATE INDEX IF NOT EXISTS idx_rule_trace_session_open
    ON aryx_rule_trace_session (started_at)
    WHERE status = 'open';

CREATE TABLE IF NOT EXISTS aryx_rule_trace_entry (
    id         BIGSERIAL PRIMARY KEY,
    run_id     TEXT NOT NULL REFERENCES aryx_rule_trace_session (run_id),
    seq_no     INTEGER NOT NULL,
    pass_num   INTEGER NOT NULL,
    rule_type  TEXT NOT NULL,
    rule_id    TEXT NOT NULL,
    attr       TEXT,
    outcome    TEXT NOT NULL,
    bml_tier   TEXT,
    fired_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rule_trace_entry_run_id
    ON aryx_rule_trace_entry (run_id, seq_no);
