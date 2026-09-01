-- Oracle equivalent of migrations/0039_entity_ontology_type_ci_idx.sql —
-- case-insensitive ontology_type lookup index for aryx_entity, closing the
-- same full-scan performance problem aryx.cpq.rdb.fetch_entities_by_exact_
-- type()'s lower(ontology_type) filter causes on Postgres (see that
-- migration's comment for the confirmed-live incident).
--
-- ONLINE builds the index without blocking concurrent DML on aryx_entity
-- (a live ingestion write target), mirroring Postgres's CONCURRENTLY.
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_entity_ws_type_lower
    ON aryx_entity (workspace_id, LOWER(ontology_type)) ONLINE';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN RAISE; END IF;
END;
/
