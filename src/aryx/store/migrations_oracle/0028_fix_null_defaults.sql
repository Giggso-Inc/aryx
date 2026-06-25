-- Oracle ADB 23ai: fix DEFAULT '' (= NULL) to DEFAULT ' ' on all affected tables.
-- Idempotent: ALTER TABLE MODIFY on an already-correct column is a no-op.
-- Needed for systems deployed before this fix was applied to the CREATE TABLE statements.

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_job MODIFY (detail DEFAULT '' '')';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_job_event MODIFY (detail DEFAULT '' '')';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_ask_history MODIFY (answer_model DEFAULT '' '')';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_ontology_version MODIFY (label DEFAULT '' '', created_by DEFAULT '' '')';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_ontology_change_log MODIFY (actor DEFAULT '' '')';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_mcp_token MODIFY (label DEFAULT '' '')';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_datasource MODIFY (secret_cipher DEFAULT '' '', secret_mask DEFAULT '' '')';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_ingest_question MODIFY (job_id DEFAULT '' '', suggested DEFAULT '' '', answer DEFAULT '' '', answered_by DEFAULT '' '')';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_relationship_type MODIFY (description DEFAULT '' '')';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_workspace MODIFY (description DEFAULT '' '', context DEFAULT '' '')';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/
