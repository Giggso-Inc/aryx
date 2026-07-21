BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_landed_ws_source ON aryx_landed_record
    (workspace_id, source_system, source_dataset, id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 AND SQLCODE != -1408 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_member_ws_landed_entity ON aryx_entity_member
    (workspace_id, landed_record_id, entity_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 AND SQLCODE != -1408 THEN RAISE; END IF;
END;
/
