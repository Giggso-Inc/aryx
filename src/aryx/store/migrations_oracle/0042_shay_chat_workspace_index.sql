-- Oracle equivalent of migrations/0042_shay_chat_workspace_index.sql -- see
-- that file's comment for the full rationale.

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_shay_chat_map_workspace ON aryx_shay_chat_map (aryx_workspace_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_shay_chat_turn_workspace ON aryx_shay_chat_turn (aryx_workspace_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/
