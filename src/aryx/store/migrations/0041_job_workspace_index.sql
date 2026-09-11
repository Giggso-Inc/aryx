-- 2026-09-11: aryx_job had no index covering workspace_id despite being the
-- actual filter in 6+ real call sites (select_job_total.sql,
-- select_job_summary.sql, select_active_workspace_job.sql,
-- delete_jobs_by_workspace.sql, purge_workspace_data.sql x2) -- only
-- idx_job_finished (finished_at) existed. Confirmed via a full-system
-- Oracle-ADB data-map review (docs/Oracle_ADB_Data_Map.xlsx, Issues sheet).
-- (workspace_id, status) also covers select_job_summary.sql's
-- `GROUP BY status` aggregate.
CREATE INDEX IF NOT EXISTS idx_job_workspace ON aryx_job (workspace_id, status);
