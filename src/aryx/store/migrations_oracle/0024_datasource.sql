-- Oracle ADB 23ai: datasource registry with encrypted secrets.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_datasource (
    id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id  NUMBER(19) NOT NULL REFERENCES aryx_workspace (id) ON DELETE CASCADE,
    name          VARCHAR2(4000) NOT NULL,
    kind          VARCHAR2(4000) NOT NULL,
    config_json   JSON DEFAULT ''{}'',
    secret_cipher VARCHAR2(4000) DEFAULT '''' NOT NULL,
    secret_mask   VARCHAR2(4000) DEFAULT '''' NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    UNIQUE (workspace_id, name)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX aryx_datasource_ws_idx ON aryx_datasource (workspace_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_secret_audit (
    id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    datasource_id NUMBER(19) NOT NULL REFERENCES aryx_datasource (id) ON DELETE CASCADE,
    action        VARCHAR2(4000) NOT NULL,
    actor         VARCHAR2(4000) DEFAULT ''system'' NOT NULL,
    at            TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
