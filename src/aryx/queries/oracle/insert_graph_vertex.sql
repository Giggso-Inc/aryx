-- Oracle ADB 23ai: plain INSERT for entity vertices, used only by the
-- full-rebuild path (project_graph -> clear() then rewrite everything).
-- Safe there because clear() guarantees no existing rows can conflict --
-- unlike merge_graph_vertex.sql (used by the incremental path, where
-- rows legitimately may already exist and need MERGE's upsert).
--
-- Live-measured (docs/ingestion/SPARK_PARALLEL_MIGRATION_ANALYSIS_2026-
-- 09-23.md Phase 4 Part B follow-up): a 500-row MERGE executemany() batch
-- hung for 180+ seconds against a real Oracle ADB even with zero
-- conflicting rows and zero lock contention (confirmed on a never-before-
-- touched workspace); the equivalent plain INSERT executemany() batch
-- completed in well under a second. MERGE's per-row existence-check is
-- not just modestly more expensive here -- it is effectively unusable
-- for this write pattern in this environment.
-- Params: :ws=workspace_id  :eid=entity_id  :typ=ontology_type
--         :name=display_name  :iri=iri  :attrs=attributes_json
INSERT INTO aryx_graph_vertex (workspace_id, entity_id, type, name, iri, attributes)
VALUES (:ws, :eid, :typ, :name, :iri, :attrs)
