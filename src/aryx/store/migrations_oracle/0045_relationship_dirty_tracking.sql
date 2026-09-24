-- G8 fix: relationship-only changes were invisible to incremental projection
-- (Oracle ADB 23ai). See migrations/0045_relationship_dirty_tracking.sql for
-- the full rationale -- this is the Oracle-syntax equivalent.

DECLARE
  l_exists NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_exists
  FROM user_tab_columns
  WHERE table_name = 'ARYX_RELATIONSHIP' AND column_name = 'UPDATED_AT';
  IF l_exists = 0 THEN
    EXECUTE IMMEDIATE 'ALTER TABLE aryx_relationship ADD updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL';
  END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_rel_ws_updated ON aryx_relationship (workspace_id, updated_at)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 AND SQLCODE != -1408 THEN RAISE; END IF;
END;
/
