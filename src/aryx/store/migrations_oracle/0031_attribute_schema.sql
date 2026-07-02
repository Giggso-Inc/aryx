-- Aryx attribute schema column for ontology types (Oracle ADB 23ai).
-- Stores per-column semantic metadata wired from aryx_field_tag after each run.
-- CLOB is used for JSON storage; Oracle 23ai treats it as JSON-compatible.
DECLARE
  l_exists NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_exists
  FROM user_tab_columns
  WHERE table_name = 'ARYX_ONTOLOGY_TYPE' AND column_name = 'ATTRIBUTE_SCHEMA';
  IF l_exists = 0 THEN
    EXECUTE IMMEDIATE 'ALTER TABLE aryx_ontology_type ADD attribute_schema CLOB DEFAULT ''{}''';
  END IF;
END;
/
