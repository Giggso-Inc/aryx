-- Oracle equivalent of migrations/0037_rule_trace.sql — durable storage for
-- CPQ rule-execution traces (docs/CPQ_RULE_EXPORT_AND_TRACE_TDD_PLAN.md).
--
-- Postgres's partial index (WHERE status = 'open') has no direct Oracle
-- equivalent; a function-based index on a CASE expression that evaluates to
-- NULL for non-'open' rows achieves the same effect, since Oracle B-tree
-- indexes omit fully-NULL entries by default.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_rule_trace_session (
    run_id         VARCHAR2(64)             NOT NULL,
    workspace_id   NUMBER(10)               NOT NULL,
    catalog_prefix VARCHAR2(64)             DEFAULT '' '' NOT NULL,
    file_key       VARCHAR2(4000)           NOT NULL,
    started_at     TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    sealed_at      TIMESTAMP WITH TIME ZONE,
    status         VARCHAR2(32)             DEFAULT ''open'' NOT NULL,
    CONSTRAINT pk_aryx_rule_trace_session PRIMARY KEY (run_id),
    CONSTRAINT chk_rule_trace_session_status
        CHECK (status IN (''open'', ''post_approval'', ''orphaned_timeout''))
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_rule_trace_session_open
    ON aryx_rule_trace_session (CASE WHEN status = ''open'' THEN started_at END)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_rule_trace_entry (
    id         NUMBER GENERATED ALWAYS AS IDENTITY,
    run_id     VARCHAR2(64)             NOT NULL,
    seq_no     NUMBER(10)               NOT NULL,
    pass_num   NUMBER(10)               NOT NULL,
    rule_type  VARCHAR2(64)             NOT NULL,
    rule_id    VARCHAR2(128)            NOT NULL,
    attr       VARCHAR2(4000),
    outcome    VARCHAR2(64)             NOT NULL,
    bml_tier   VARCHAR2(32),
    fired_at   TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT pk_aryx_rule_trace_entry PRIMARY KEY (id),
    CONSTRAINT fk_rule_trace_entry_run FOREIGN KEY (run_id)
        REFERENCES aryx_rule_trace_session (run_id)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_rule_trace_entry_run_id
    ON aryx_rule_trace_entry (run_id, seq_no)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/
