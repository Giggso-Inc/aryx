-- Oracle ADB 23ai: survivorship (attribute conflicts + workspace policy).
-- survivorship column already included in aryx_workspace in 0009.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_attribute_conflict (
    id             NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id   NUMBER(19) NOT NULL,
    entity_id      NUMBER(19) NOT NULL,
    attribute      VARCHAR2(4000) NOT NULL,
    winning_value  JSON,
    losing_values  JSON NOT NULL,
    strategy       VARCHAR2(4000) NOT NULL,
    decided_at     TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_conflict_entity ON aryx_attribute_conflict (workspace_id, entity_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;

/