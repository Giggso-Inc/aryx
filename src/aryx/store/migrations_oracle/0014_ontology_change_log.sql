-- Oracle ADB 23ai: ontology change log.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_ontology_change_log (
    id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id  NUMBER(19) NOT NULL,
    actor         VARCHAR2(4000) DEFAULT '''' NOT NULL,
    op            VARCHAR2(100) NOT NULL,
    target_kind   VARCHAR2(100) NOT NULL,
    target_name   VARCHAR2(4000) NOT NULL,
    before_json   JSON,
    after_json    JSON,
    changed_at    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_change_log_ws_time ON aryx_ontology_change_log (workspace_id, changed_at DESC)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;

/