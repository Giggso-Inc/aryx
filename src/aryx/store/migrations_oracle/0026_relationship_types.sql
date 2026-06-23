-- Oracle ADB 23ai: declared relationship types.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_relationship_type (
    id           NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id NUMBER(19) NOT NULL REFERENCES aryx_workspace (id) ON DELETE CASCADE,
    name         VARCHAR2(4000) NOT NULL,
    source_type  VARCHAR2(4000) NOT NULL,
    target_type  VARCHAR2(4000) NOT NULL,
    description  VARCHAR2(4000) DEFAULT '''' NOT NULL,
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    UNIQUE (workspace_id, source_type, name, target_type)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX aryx_relationship_type_ws_idx ON aryx_relationship_type (workspace_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
