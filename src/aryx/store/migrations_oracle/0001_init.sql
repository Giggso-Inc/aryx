-- Oracle ADB 23ai: Aryx landing schema.
-- Translated from Postgres 0001_init.sql.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_run (
    run_id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_system  VARCHAR2(4000) NOT NULL,
    source_dataset VARCHAR2(4000) NOT NULL,
    status         VARCHAR2(100) DEFAULT ''running'' NOT NULL,
    record_count   NUMBER(10)    DEFAULT 0           NOT NULL,
    started_at     TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    finished_at    TIMESTAMP WITH TIME ZONE
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_landed_record (
    id               NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id           NUMBER NOT NULL REFERENCES aryx_run (run_id),
    source_system    VARCHAR2(4000) NOT NULL,
    source_dataset   VARCHAR2(4000) NOT NULL,
    source_record_id VARCHAR2(4000) NOT NULL,
    payload          JSON NOT NULL,
    cleaned_at       TIMESTAMP WITH TIME ZONE NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_landed_run ON aryx_landed_record (run_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_landed_provenance ON aryx_landed_record (source_system, source_dataset, source_record_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_field_profile (
    id              NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          NUMBER NOT NULL REFERENCES aryx_run (run_id),
    field           VARCHAR2(4000) NOT NULL,
    non_null        NUMBER(10) NOT NULL,
    distinct_count  NUMBER(10) NOT NULL,
    distinct_capped CHAR(1) DEFAULT ''N'' CHECK (distinct_capped IN (''Y'',''N'')),
    samples         JSON NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;

/