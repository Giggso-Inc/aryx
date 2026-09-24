-- Oracle ADB 23ai: plain INSERT for relationship edges, used only by the
-- full-rebuild path (project_graph -> clear() then rewrite everything).
-- Safe there because clear() guarantees no existing rows can conflict --
-- unlike merge_graph_edge.sql (used by the incremental path). See
-- insert_graph_vertex.sql for the live-measured rationale (MERGE
-- executemany() batches were found to hang for 180+ seconds on a
-- completely fresh, conflict-free workspace; plain INSERT executemany()
-- completed in well under a second for the same row count).
-- Params: :ws=workspace_id  :src=src_id  :tgt=tgt_id  :name=name
INSERT INTO aryx_graph_edge (workspace_id, src_id, tgt_id, name)
VALUES (:ws, :src, :tgt, :name)
