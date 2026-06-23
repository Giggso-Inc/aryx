-- Oracle ADB 23ai: ontology axioms.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_ontology_axiom (
    id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id  NUMBER(19) NOT NULL,
    subject_type  VARCHAR2(4000) NOT NULL,
    kind          VARCHAR2(100) NOT NULL,
    payload       JSON DEFAULT ''{}'',
    payload_hash  VARCHAR2(4000) NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    UNIQUE (workspace_id, subject_type, kind, payload_hash)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_axiom_ws_subject ON aryx_ontology_axiom (workspace_id, subject_type)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_axiom_violation (
    id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id  NUMBER(19) NOT NULL,
    entity_id     NUMBER(19) NOT NULL,
    axiom_id      NUMBER(19) NOT NULL REFERENCES aryx_ontology_axiom (id) ON DELETE CASCADE,
    reason        CLOB NOT NULL,
    detected_at   TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_violation_ws_entity ON aryx_axiom_violation (workspace_id, entity_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
