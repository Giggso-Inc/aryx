UPDATE aryx_job
   SET status = 'failed',
       error  = 'timeout — ingest function did not report completion',
       pct    = 100, finished_at = now(), updated_at = now()
 WHERE status NOT IN ('complete', 'failed')
   AND updated_at < now() - (%s * INTERVAL '1 minute')
