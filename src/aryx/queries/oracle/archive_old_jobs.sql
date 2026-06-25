-- Oracle ADB 23ai: archive completed jobs older than :1 days.
-- NOT EXISTS used instead of ON CONFLICT — avoids ORA-00001 aborting a multi-row INSERT SELECT.
INSERT INTO aryx_job_archive (job_id, source_system, source_dataset, status,
    stage, pct, detail, run_id, error, started_at, updated_at, finished_at)
SELECT job_id, source_system, source_dataset, status, stage, pct, detail,
       run_id, error, started_at, updated_at, finished_at
FROM aryx_job j
WHERE j.finished_at IS NOT NULL
  AND j.finished_at < SYSDATE - :1
  AND NOT EXISTS (SELECT 1 FROM aryx_job_archive a WHERE a.job_id = j.job_id)
