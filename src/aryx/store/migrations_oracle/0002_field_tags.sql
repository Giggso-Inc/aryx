-- Oracle ADB 23ai: field tags.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_field_tag (
    id            NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id        NUMBER NOT NULL REFERENCES aryx_run (run_id),
    field         VARCHAR2(4000) NOT NULL,
    semantic_type VARCHAR2(4000) NOT NULL,
    is_pii        CHAR(1) DEFAULT ''N'' CHECK (is_pii IN (''Y'',''N''))
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_tag_run ON aryx_field_tag (run_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;

/