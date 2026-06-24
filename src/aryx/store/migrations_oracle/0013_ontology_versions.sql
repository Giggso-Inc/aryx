-- Oracle ADB 23ai: ontology version snapshots.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_ontology_version (
    id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id  NUMBER(19) NOT NULL,
    version_no    NUMBER(10) NOT NULL,
    label         VARCHAR2(4000) DEFAULT '''' NOT NULL,
    types_json    JSON NOT NULL,
    rules_json    JSON DEFAULT ''[]'',
    created_by    VARCHAR2(4000) DEFAULT '''' NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    UNIQUE (workspace_id, version_no)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_version_ws ON aryx_ontology_version (workspace_id, version_no DESC)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;

/