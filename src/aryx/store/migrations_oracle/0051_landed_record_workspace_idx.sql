-- Oracle-only: index aryx_landed_record.workspace_id.
--
-- 0030_landed_record_workspace.sql added workspace_id to this table but
-- never indexed it (Postgres needs no equivalent -- 0009_workspaces.sql
-- recreated aryx_landed_record as a partitioned table there, so
-- partition pruning does this job for free on that backend).
--
-- Confirmed live, 2026-10-07: DELETE FROM aryx_landed_record WHERE
-- workspace_id = :1 (the first of four tables OracleWorkspaceStore.delete()
-- clears per workspace, see oracle_workspace.py's _drop_partitions) full-
-- table-scans all ~7.9M rows in this table to find a workspace's (possibly
-- zero) matching rows, exceeding the 30s Oracle call_timeout and failing
-- the whole workspace deletion with DPY-4024/ORA-03156 -- for EVERY
-- workspace, not just large ones, since the scan cost doesn't depend on
-- how much of that 7.9M belongs to the workspace being deleted.

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_landed_record_workspace ON aryx_landed_record (workspace_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 AND SQLCODE != -1408 THEN RAISE; END IF;
END;
/
