DELETE FROM aryx_graph_source
WHERE workspace_id = :1
  AND system = :2
  AND dataset = :3
