-- Oracle ADB 23ai: incremental projection watermark + projected-id side table.
-- updated_at column already included in aryx_entity in 0004.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_projection_state (
    workspace_id      NUMBER(19) PRIMARY KEY,
    last_projected_at TIMESTAMP WITH TIME ZONE NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_projected_entity (
    workspace_id NUMBER(19) NOT NULL,
    entity_id    NUMBER(19) NOT NULL,
    CONSTRAINT pk_projected_entity PRIMARY KEY (workspace_id, entity_id)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;

/