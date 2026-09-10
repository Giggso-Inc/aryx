-- Oracle ADB 23ai: Property Graph backing tables + graph DDL.
-- Run after 0027 migrations complete.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_graph_vertex (
    workspace_id NUMBER(19) NOT NULL,
    entity_id    NUMBER(19) NOT NULL,
    type         VARCHAR2(4000),
    name         VARCHAR2(4000),
    iri          VARCHAR2(4000),
    attributes   JSON DEFAULT ''{}'',
    CONSTRAINT pk_graph_vertex PRIMARY KEY (workspace_id, entity_id)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_graph_vertex_type ON aryx_graph_vertex (workspace_id, type)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_graph_edge (
    edge_id      NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id NUMBER(19) NOT NULL,
    src_id       NUMBER(19) NOT NULL,
    tgt_id       NUMBER(19) NOT NULL,
    name         VARCHAR2(4000) NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_graph_edge ADD (edge_id NUMBER GENERATED ALWAYS AS IDENTITY)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_graph_edge ADD CONSTRAINT pk_graph_edge PRIMARY KEY (edge_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -2260 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_graph_edge_src ON aryx_graph_edge (workspace_id, src_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_graph_edge_tgt ON aryx_graph_edge (workspace_id, tgt_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

-- 2026-09-10: OracleGraphReader.subgraph() (graph/oracle_graph_reader_
-- traverse.py) filters on (workspace_id, name) twice per call -- once for
-- `SELECT DISTINCT name ... WHERE workspace_id = :1` (the relationship-type
-- discovery scan) and once per relationship type for the proportional
-- sample (`WHERE workspace_id = :ws AND name = :rel`) -- with no index
-- covering that column pair, both require a full scan of every edge in the
-- workspace. This is the exact same performance shape as the FalkorDB
-- GraphReader.subgraph() incident fixed in docs/GRAPH_SUBGRAPH_LARGE_
-- WORKSPACE_PERFORMANCE_2026_09_02.md (dev-rv-msi #316, ported to dev_oci
-- 2026-09-10) -- confirmed via this table's own DDL above that, unlike
-- FalkorDB's r.name index (already present there), no equivalent index
-- exists here at all.
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_graph_edge_workspace_name ON aryx_graph_edge (workspace_id, name)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_graph_source (
    workspace_id NUMBER(19) NOT NULL,
    source_id    NUMBER GENERATED ALWAYS AS IDENTITY,
    system       VARCHAR2(4000),
    dataset      VARCHAR2(4000),
    record_id    VARCHAR2(4000),
    CONSTRAINT pk_graph_source PRIMARY KEY (workspace_id, source_id)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_graph_provenance (
    workspace_id NUMBER(19) NOT NULL,
    entity_id    NUMBER(19) NOT NULL,
    source_id    NUMBER(19) NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_graph_prov_entity ON aryx_graph_provenance (workspace_id, entity_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

-- Unique constraints required for Oracle MERGE ON clause idempotency.
-- Without these, duplicate rows cause ORA-30926 on any subsequent projection run.

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_graph_source ADD CONSTRAINT uq_graph_source UNIQUE (workspace_id, system, dataset, record_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -2261 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_graph_provenance ADD CONSTRAINT pk_graph_prov PRIMARY KEY (workspace_id, entity_id, source_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -2260 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_graph_edge ADD CONSTRAINT uq_graph_edge UNIQUE (workspace_id, src_id, tgt_id, name)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -2261 THEN RAISE; END IF;
END;
/

-- Oracle Property Graph declaration (23ai SQL/PGQ).
-- VERTEX TABLES and EDGE TABLES map directly to the backing tables above.
BEGIN
  EXECUTE IMMEDIATE '
    CREATE PROPERTY GRAPH aryx_knowledge_graph
      VERTEX TABLES (
        aryx_graph_vertex
          KEY (workspace_id, entity_id)
          PROPERTIES (type, name, iri, attributes)
      )
      EDGE TABLES (
        aryx_graph_edge
          SOURCE KEY (workspace_id, src_id) REFERENCES aryx_graph_vertex (workspace_id, entity_id)
          DESTINATION KEY (workspace_id, tgt_id) REFERENCES aryx_graph_vertex (workspace_id, entity_id)
          LABEL relationship
          PROPERTIES (name)
      )
  ';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/
