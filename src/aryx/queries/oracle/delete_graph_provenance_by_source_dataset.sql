DELETE FROM aryx_graph_provenance
WHERE workspace_id = :1
  AND source_id IN (
    SELECT source_id
    FROM aryx_graph_source
    WHERE workspace_id = :1
      AND system = :2
      AND dataset = :3
  )
