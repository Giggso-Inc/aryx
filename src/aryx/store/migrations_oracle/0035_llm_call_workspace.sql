-- 0035 — Add workspace_id to aryx_llm_call (Oracle ADB 23ai).
-- Postgres migration 0031 added this column; the Oracle side was missed.
-- Existing rows are backfilled to workspace_id=1 (the default workspace).

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_llm_call ADD (workspace_id NUMBER(19) DEFAULT 1 NOT NULL)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_llm_call_ws_ts ON aryx_llm_call (workspace_id, ts DESC)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/
