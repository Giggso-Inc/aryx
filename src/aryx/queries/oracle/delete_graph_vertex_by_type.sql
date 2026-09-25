-- Oracle ADB 23ai: remove every vertex of a type.
-- Params: :ws=workspace_id  :typ=ontology_type
DELETE FROM aryx_graph_vertex
WHERE workspace_id = :ws AND type = :typ
