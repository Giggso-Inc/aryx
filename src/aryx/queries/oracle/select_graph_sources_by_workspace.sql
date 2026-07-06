SELECT source_id, system, dataset, record_id
FROM aryx_graph_source
WHERE workspace_id = :1
