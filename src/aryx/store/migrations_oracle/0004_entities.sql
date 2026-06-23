-- Oracle ADB 23ai: resolved entities + members.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_entity (
    id            NUMBER GENERATED ALWAYS AS IDENTITY,
    workspace_id  NUMBER NOT NULL DEFAULT 1,
    ontology_type VARCHAR2(4000) NOT NULL,
    attributes    JSON DEFAULT ''{}'',
    confidence    FLOAT DEFAULT 0 NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    PRIMARY KEY (id, workspace_id)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_entity_member (
    id               NUMBER GENERATED ALWAYS AS IDENTITY,
    workspace_id     NUMBER NOT NULL DEFAULT 1,
    entity_id        NUMBER NOT NULL,
    landed_record_id NUMBER NOT NULL,
    confidence       FLOAT DEFAULT 1 NOT NULL,
    PRIMARY KEY (id, workspace_id)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_member_entity ON aryx_entity_member (workspace_id, entity_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_member_record ON aryx_entity_member (workspace_id, landed_record_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_entity_ws_type ON aryx_entity (workspace_id, ontology_type)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
