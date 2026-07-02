-- Oracle ADB 23ai: upsert one entity vertex.
-- Params: :ws=workspace_id  :eid=entity_id  :typ=ontology_type
--         :name=display_name  :iri=iri  :attrs=attributes_json
MERGE INTO aryx_graph_vertex t
USING (SELECT :ws AS workspace_id, :eid AS entity_id FROM dual) s
ON (t.workspace_id = s.workspace_id AND t.entity_id = s.entity_id)
WHEN MATCHED THEN
    UPDATE SET t.type = :typ, t.name = :name,
               t.iri = :iri, t.attributes = :attrs
WHEN NOT MATCHED THEN
    INSERT (workspace_id, entity_id, type, name, iri, attributes)
    VALUES (:ws, :eid, :typ, :name, :iri, :attrs)
