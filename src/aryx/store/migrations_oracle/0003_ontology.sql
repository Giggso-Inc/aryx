-- Oracle ADB 23ai: ontology types + schema mappings.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_ontology_type (
    id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       VARCHAR2(4000) NOT NULL UNIQUE,
    attributes JSON DEFAULT ''[]'',
    status     VARCHAR2(100) DEFAULT ''proposed'' NOT NULL,
    source     VARCHAR2(100) DEFAULT ''agent'' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_schema_mapping (
    id                 NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id             NUMBER REFERENCES aryx_run (run_id),
    source_system      VARCHAR2(4000) NOT NULL,
    source_dataset     VARCHAR2(4000) NOT NULL,
    source_field       VARCHAR2(4000),
    ontology_type      VARCHAR2(4000) NOT NULL,
    ontology_attribute VARCHAR2(4000),
    confidence         FLOAT DEFAULT 0 NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_mapping_run ON aryx_schema_mapping (run_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
