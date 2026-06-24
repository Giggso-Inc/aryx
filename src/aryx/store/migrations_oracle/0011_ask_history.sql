-- Oracle ADB 23ai: ask history.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_ask_history (
    id                NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id      NUMBER(19) NOT NULL,
    asked_at          TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    question          CLOB NOT NULL,
    answer            CLOB NOT NULL,
    tools_called      JSON DEFAULT ''[]'',
    entity_ids        CLOB DEFAULT ''[]'',
    prompt_tokens     NUMBER(10) DEFAULT 0 NOT NULL,
    completion_tokens NUMBER(10) DEFAULT 0 NOT NULL,
    latency_ms        NUMBER(10) DEFAULT 0 NOT NULL,
    answer_model      VARCHAR2(4000) DEFAULT '''' NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_ask_history_ws_time ON aryx_ask_history (workspace_id, asked_at DESC)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;

/