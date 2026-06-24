-- Oracle ADB 23ai: ontology inference rules.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_ontology_rule (
    id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id  NUMBER(19) NOT NULL,
    name          VARCHAR2(4000) NOT NULL,
    when_clause   JSON NOT NULL,
    then_clause   JSON NOT NULL,
    enabled       CHAR(1) DEFAULT ''Y'' CHECK (enabled IN (''Y'',''N'')),
    fires_count   NUMBER(10) DEFAULT 0 NOT NULL,
    last_run_at   TIMESTAMP WITH TIME ZONE,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    UNIQUE (workspace_id, name)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_rule_ws_enabled ON aryx_ontology_rule (workspace_id, enabled)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;

/