-- Oracle ADB 23ai: clear all graph edges for a workspace.
-- Params: :1=workspace_id
DELETE FROM aryx_graph_edge WHERE workspace_id = :1
