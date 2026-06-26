-- Oracle ADB 23ai: add workspace_id to aryx_landed_record.
-- Postgres 0009_workspaces.sql recreated aryx_landed_record as a partitioned
-- table with workspace_id; the Oracle equivalent only added workspace_id to
-- aryx_run and missed aryx_landed_record. This closes the gap.

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_landed_record ADD (workspace_id NUMBER(19) DEFAULT 1 NOT NULL)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
/
