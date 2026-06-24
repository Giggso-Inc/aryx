-- Oracle ADB 23ai: LLM call log.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_llm_call (
    id                NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    role              VARCHAR2(4000) NOT NULL,
    model             VARCHAR2(4000) NOT NULL,
    provider          VARCHAR2(100) DEFAULT ''ollama'' NOT NULL,
    prompt_tokens     NUMBER(10) DEFAULT 0 NOT NULL,
    completion_tokens NUMBER(10) DEFAULT 0 NOT NULL,
    latency_ms        NUMBER(10) DEFAULT 0 NOT NULL,
    source            VARCHAR2(100) DEFAULT ''ask'' NOT NULL,
    error             CLOB,
    ts                TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_llm_call_ts ON aryx_llm_call (ts)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;

/