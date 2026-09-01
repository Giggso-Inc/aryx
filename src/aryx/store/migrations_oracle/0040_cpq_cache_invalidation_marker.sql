-- Oracle equivalent of migrations/0040_cpq_cache_invalidation_marker.sql —
-- single-row shared "last changed" clock every worker polls to notice a
-- re-ingest it didn't itself handle (docs/CPQ_ASK_THREADS_MESSAGE_
-- CONCURRENCY_DELAY report, Section 12).

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE cpq_cache_invalidation_marker (
    id             NUMBER(1)                DEFAULT 1 NOT NULL,
    invalidated_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    last_job_id    VARCHAR2(4000),
    CONSTRAINT pk_cpq_cache_invalidation_marker PRIMARY KEY (id),
    CONSTRAINT chk_cpq_cache_invalidation_marker_single_row CHECK (id = 1)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

-- ON CONFLICT (id) DO NOTHING equivalent: a re-run hits ORA-00001 (unique
-- constraint violated) on the existing single row and is swallowed here.
BEGIN
  EXECUTE IMMEDIATE 'INSERT INTO cpq_cache_invalidation_marker (id, invalidated_at)
    VALUES (1, SYSTIMESTAMP)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1 THEN RAISE; END IF;
END;
/
