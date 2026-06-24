-- Oracle ADB 23ai: block-wise resolution checkpoints + run stages.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_block_member (
    run_id    NUMBER(19) NOT NULL,
    block_key VARCHAR2(4000) NOT NULL,
    record_id NUMBER(19) NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_block_member_key ON aryx_block_member (run_id, block_key)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_block_done (
    run_id    NUMBER(19) NOT NULL,
    block_key VARCHAR2(4000) NOT NULL,
    CONSTRAINT pk_block_done PRIMARY KEY (run_id, block_key)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_match_edge (
    run_id   NUMBER(19) NOT NULL,
    left_id  NUMBER(19) NOT NULL,
    right_id NUMBER(19) NOT NULL,
    score    BINARY_FLOAT NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_match_edge_run ON aryx_match_edge (run_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_run_stage (
    run_id      NUMBER(19) NOT NULL,
    stage       VARCHAR2(4000) NOT NULL,
    status      VARCHAR2(100) NOT NULL DEFAULT ''running'',
    started_at  TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    finished_at TIMESTAMP WITH TIME ZONE,
    detail      JSON DEFAULT ''{}'',
    CONSTRAINT pk_run_stage PRIMARY KEY (run_id, stage)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
