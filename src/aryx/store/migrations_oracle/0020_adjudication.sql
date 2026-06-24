-- Oracle ADB 23ai: human adjudication queue.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_adjudication (
    id              NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id    NUMBER(19) NOT NULL,
    run_id          NUMBER(19) NOT NULL,
    left_record_id  NUMBER(19) NOT NULL,
    right_record_id NUMBER(19) NOT NULL,
    score           BINARY_FLOAT NOT NULL,
    llm_verdict     CHAR(1) CHECK (llm_verdict IN (''Y'',''N'')),
    llm_reason      CLOB,
    status          VARCHAR2(100) DEFAULT ''pending'' NOT NULL,
    decided_by      VARCHAR2(4000),
    decided_at      TIMESTAMP WITH TIME ZONE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_adj_pending ON aryx_adjudication (workspace_id, status)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;

/