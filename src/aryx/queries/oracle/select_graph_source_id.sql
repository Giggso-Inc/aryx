-- Oracle ADB 23ai: fetch source_id for a system+dataset+record triplet.
-- Params: :1=workspace_id  :2=system  :3=dataset  :4=record_id
SELECT source_id
FROM   aryx_graph_source
WHERE  workspace_id = :1
  AND  system       = :2
  AND  dataset      = :3
  AND  record_id    = :4
