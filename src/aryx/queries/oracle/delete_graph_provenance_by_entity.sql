-- Oracle ADB 23ai: remove all provenance links for one entity.
-- Params: :1=workspace_id  :2=entity_id
DELETE FROM aryx_graph_provenance
WHERE workspace_id = :1 AND entity_id = :2
