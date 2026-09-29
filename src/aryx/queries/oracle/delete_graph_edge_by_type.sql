-- Oracle ADB 23ai: remove every edge touching a vertex of a type, as
-- either source or target.
-- Params: :ws=workspace_id  :typ=ontology_type
DELETE FROM aryx_graph_edge
WHERE workspace_id = :ws
  AND (
    src_id IN (SELECT entity_id FROM aryx_graph_vertex WHERE workspace_id = :ws AND type = :typ)
    OR tgt_id IN (SELECT entity_id FROM aryx_graph_vertex WHERE workspace_id = :ws AND type = :typ)
  )
