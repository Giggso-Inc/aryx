-- Oracle ADB 23ai: remove provenance links for every entity of a type.
-- Params: :ws=workspace_id  :typ=ontology_type
DELETE FROM aryx_graph_provenance
WHERE workspace_id = :ws
  AND entity_id IN (
    SELECT entity_id FROM aryx_graph_vertex
    WHERE workspace_id = :ws AND type = :typ
  )
