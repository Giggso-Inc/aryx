-- CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md: per-workspace,
-- uploaded replacement for the hardcoded config_layouts/ folder.
-- Oracle ADB version. VARCHAR2 for short strings, CLOB for the layout
-- content itself (plain JSON text, no gzip/base64 wrapping needed --
-- see discovery_store_codec.py's docstring for why that wrapper exists
-- for binary payloads and doesn't apply here).

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_cpq_layout_file (
    layout_id      VARCHAR2(64)              NOT NULL,
    workspace_id   NUMBER(10)                NOT NULL,
    catalog_prefix VARCHAR2(256)             NOT NULL,
    filename       VARCHAR2(256)             NOT NULL,
    content_clob   CLOB                      NOT NULL,
    status         VARCHAR2(32)  DEFAULT ''active'' NOT NULL,
    uploaded_at    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT pk_aryx_cpq_layout_file PRIMARY KEY (layout_id)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE UNIQUE INDEX idx_aryx_cpq_layout_ws_catalog
    ON aryx_cpq_layout_file (workspace_id, catalog_prefix)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/
