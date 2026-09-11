-- Oracle equivalent of migrations/0041_job_workspace_index.sql -- see that
-- file's comment for the full rationale (aryx_job had no index covering
-- workspace_id despite 6+ real call sites filtering by it).

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_job_workspace ON aryx_job (workspace_id, status)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 AND SQLCODE != -1408 THEN RAISE; END IF;
END;
/
