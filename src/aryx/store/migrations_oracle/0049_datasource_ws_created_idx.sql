-- Oracle equivalent of migrations/0049_datasource_ws_created_idx.sql --
-- see that file's comment for the full rationale.

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_datasource_ws_created ON aryx_datasource (workspace_id, created_at DESC)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 AND SQLCODE != -1408 THEN RAISE; END IF;
END;
/
