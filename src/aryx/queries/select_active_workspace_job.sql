SELECT job_id, status
FROM aryx_job
WHERE workspace_id = %s
  AND status IN ('queued', 'running')
ORDER BY started_at
FETCH FIRST 1 ROW ONLY
