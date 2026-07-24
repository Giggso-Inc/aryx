SELECT
    aryx_shay_workspace_map.shay_workspace_id::text,
    aryx_shay_workspace_map.aryx_workspace_id
FROM aryx_shay_workspace_map
JOIN gg_workspace
    ON gg_workspace.id = aryx_shay_workspace_map.shay_workspace_id
WHERE aryx_shay_workspace_map.shay_workspace_id = %s::uuid
  AND aryx_shay_workspace_map.aryx_workspace_id = %s
