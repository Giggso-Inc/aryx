-- Oracle ADB 23ai: clear all graph vertex rows for a workspace.
-- Params: :1=workspace_id
DELETE FROM aryx_graph_vertex WHERE workspace_id = :1
