-- Oracle ADB 23ai: kinetic action layer.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_action (
    id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id  NUMBER(19) NOT NULL,
    name          VARCHAR2(4000) NOT NULL,
    definition    JSON NOT NULL,
    enabled       CHAR(1) DEFAULT ''Y'' NOT NULL CHECK (enabled IN (''Y'',''N'')),
    superseded_by NUMBER(19),
    created_by    VARCHAR2(4000),
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_action_name ON aryx_action (workspace_id, name)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_action_execution (
    id           NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id NUMBER(19) NOT NULL,
    action_id    NUMBER(19) NOT NULL,
    entity_id    NUMBER(19) NOT NULL,
    params       JSON DEFAULT ''{}'',
    status       VARCHAR2(100) DEFAULT ''pending'' NOT NULL,
    requested_by VARCHAR2(4000),
    decided_by   VARCHAR2(4000),
    decided_at   TIMESTAMP WITH TIME ZONE,
    applied_at   TIMESTAMP WITH TIME ZONE,
    effect_log   JSON DEFAULT ''[]'',
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_action_exec_pending ON aryx_action_execution (workspace_id, status)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;

/