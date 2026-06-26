-- Oracle ADB 23ai: remove one entity vertex.
-- Params: :1=workspace_id  :2=entity_id
DELETE FROM aryx_graph_vertex
WHERE workspace_id = :1 AND entity_id = :2
