-- csv_bml_ingestion: tables are now per workspace (ws<id>_<file name>), so a stored run keeps both names:
-- table_name = the Oracle table actually used (what a re-run loads into), logical_table = the file-name
-- stem the BML queries use (what the UI shows). Older rows have no logical_table (NULL = same as table_name).

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_csv_ingest_run ADD (logical_table VARCHAR2(128))';
-- ORA-01430: column already exists (re-running this migration). Anything else must re-raise.
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
/
