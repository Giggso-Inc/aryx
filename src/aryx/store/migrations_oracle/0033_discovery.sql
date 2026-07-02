-- Persistent document-discovery store for /admin/docs/read+confirm.
-- Oracle ADB 23ai version. VARCHAR2 for short strings, CLOB for JSON payloads.
-- No expiry column — rows persist indefinitely.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_discovery (
    discovery_id  VARCHAR2(64)              NOT NULL,
    workspace_id  NUMBER(10)                NOT NULL,
    status        VARCHAR2(32)              DEFAULT ''pending'' NOT NULL,
    data_json     CLOB                      DEFAULT ''{}'' NOT NULL,
    summary_json  CLOB                      DEFAULT ''{}'' NOT NULL,
    file_count    NUMBER(10)                DEFAULT 0 NOT NULL,
    confirm_state CLOB                      DEFAULT ''{}'' NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE  DEFAULT SYSTIMESTAMP NOT NULL,
    confirmed_at  TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_aryx_discovery PRIMARY KEY (discovery_id)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_aryx_discovery_workspace
    ON aryx_discovery (workspace_id, created_at DESC)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/
