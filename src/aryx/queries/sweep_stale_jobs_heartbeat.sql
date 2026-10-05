UPDATE aryx_job
   SET status = 'failed',
       error  = 'worker lost — no progress reported within the heartbeat window (likely a crashed/restarted worker, not a slow job)',
       pct    = 100, finished_at = now(), updated_at = now()
 WHERE status = 'running'
   AND stage LIKE '%%CPQ Ingestion%%'
   AND updated_at < now() - (%s * INTERVAL '1 minute')
