-- Oracle ADB 23ai: clear all graph provenance rows for a workspace.
-- Params: :1=workspace_id
DELETE FROM aryx_graph_provenance WHERE workspace_id = :1
