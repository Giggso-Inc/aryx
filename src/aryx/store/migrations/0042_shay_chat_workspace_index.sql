-- 2026-09-11: aryx_shay_chat_map and aryx_shay_chat_turn both declare
-- aryx_workspace_id NOT NULL REFERENCES aryx_workspace(id) ON DELETE CASCADE
-- with no index covering that column -- unlike their sibling bridge tables
-- (aryx_shay_workspace_map's FK is UNIQUE; aryx_shay_datasource_map is
-- covered by a composite index). A workspace delete cascades into both
-- tables with no index to find the matching rows, and any per-workspace
-- chat lookup has the same full-scan cost. Confirmed via a full-system
-- Oracle-ADB data-map review (docs/Oracle_ADB_Data_Map.xlsx, Issues sheet).
CREATE INDEX IF NOT EXISTS idx_shay_chat_map_workspace ON aryx_shay_chat_map (aryx_workspace_id);
CREATE INDEX IF NOT EXISTS idx_shay_chat_turn_workspace ON aryx_shay_chat_turn (aryx_workspace_id);
