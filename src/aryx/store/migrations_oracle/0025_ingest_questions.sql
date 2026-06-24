-- Oracle ADB 23ai: HITL ingest questions queue.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_ingest_question (
    id           NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id NUMBER(19) NOT NULL REFERENCES aryx_workspace (id) ON DELETE CASCADE,
    job_id       VARCHAR2(4000) DEFAULT '''' NOT NULL,
    kind         VARCHAR2(4000) NOT NULL,
    prompt       CLOB NOT NULL,
    options_json JSON DEFAULT ''[]'',
    suggested    VARCHAR2(4000) DEFAULT '''' NOT NULL,
    status       VARCHAR2(100) DEFAULT ''pending'' NOT NULL,
    answer       VARCHAR2(4000) DEFAULT '''' NOT NULL,
    answered_by  VARCHAR2(4000) DEFAULT '''' NOT NULL,
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    answered_at  TIMESTAMP WITH TIME ZONE
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX aryx_ingest_question_ws_status_idx ON aryx_ingest_question (workspace_id, status, created_at)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX aryx_ingest_question_job_idx ON aryx_ingest_question (job_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
