-- Oracle ADB 23ai: clear all graph source rows for a workspace.
-- Params: :1=workspace_id
DELETE FROM aryx_graph_source WHERE workspace_id = :1
