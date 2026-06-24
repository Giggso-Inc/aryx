-- Oracle ADB 23ai: workspaces.
-- No table partitioning — workspace_id is a plain indexed column on each table.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_workspace (
    id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        VARCHAR2(4000) NOT NULL UNIQUE,
    description VARCHAR2(4000) DEFAULT '''' NOT NULL,
    context     VARCHAR2(4000) DEFAULT '''' NOT NULL,
    brief       JSON DEFAULT ''{}'',
    survivorship JSON DEFAULT ''{}'',
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'INSERT INTO aryx_workspace (name, description) VALUES (''Default'', ''Original workspace'')';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/

ALTER TABLE aryx_run ADD (workspace_id NUMBER(19) DEFAULT 1 NOT NULL);
