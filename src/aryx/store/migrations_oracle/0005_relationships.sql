-- Oracle ADB 23ai: entity relationships.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_relationship (
    id               NUMBER GENERATED ALWAYS AS IDENTITY,
    workspace_id     NUMBER NOT NULL DEFAULT 1,
    source_entity_id NUMBER NOT NULL,
    target_entity_id NUMBER NOT NULL,
    name             VARCHAR2(4000) NOT NULL,
    confidence       FLOAT DEFAULT 0 NOT NULL,
    PRIMARY KEY (id, workspace_id)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_rel_ws_source ON aryx_relationship (workspace_id, source_entity_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_rel_ws_target ON aryx_relationship (workspace_id, target_entity_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
