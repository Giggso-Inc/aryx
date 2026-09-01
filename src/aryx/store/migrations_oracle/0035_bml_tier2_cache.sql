-- Oracle equivalent of migrations/0035_bml_tier2_cache.sql — durable Tier-2
-- BML result cache (Amendment 18 option 4, docs/CPQ_UNIFIED_INTENT_
-- CLASSIFIER_PLAN.md). JSONB -> native JSON (Oracle ADB 23ai).

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_bml_tier2_cache (
    cache_key    VARCHAR2(64)             NOT NULL,
    workspace_id NUMBER(19)               NOT NULL,
    kind         VARCHAR2(4000)           NOT NULL,
    result       JSON,
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT pk_aryx_bml_tier2_cache PRIMARY KEY (cache_key)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_bml_tier2_cache_ws
    ON aryx_bml_tier2_cache (workspace_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/
