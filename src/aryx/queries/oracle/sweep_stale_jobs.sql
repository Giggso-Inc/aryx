UPDATE aryx_job
   SET status = 'failed',
       error  = 'timeout — ingest function did not report completion',
       pct    = 100, finished_at = SYSDATE, updated_at = SYSDATE
 WHERE status NOT IN ('complete', 'failed')
   AND updated_at < SYSDATE - :1 / 1440
