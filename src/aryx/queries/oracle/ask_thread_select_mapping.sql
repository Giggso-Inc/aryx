-- Oracle equivalent of ask_thread_select_mapping.sql. Both
-- aryx_shay_workspace_map.shay_workspace_id and gg_workspace.id are
-- VARCHAR2(36) on Oracle (UUID stored as text) -- no ::uuid/::text
-- casts needed. Params: :1=shay_workspace_id :2=aryx_workspace_id
SELECT
    aryx_shay_workspace_map.shay_workspace_id,
    aryx_shay_workspace_map.aryx_workspace_id
FROM aryx_shay_workspace_map
JOIN gg_workspace
    ON gg_workspace.id = aryx_shay_workspace_map.shay_workspace_id
WHERE aryx_shay_workspace_map.shay_workspace_id = :1
  AND aryx_shay_workspace_map.aryx_workspace_id = :2
