UPDATE aryx_job
   SET status = 'failed',
       error  = 'worker lost - no progress reported within the heartbeat window (likely a crashed/restarted worker, not a slow job)',
       pct    = 100, finished_at = SYSDATE, updated_at = SYSDATE
 WHERE status = 'running'
   AND stage LIKE '%CPQ Ingestion%'
   AND updated_at < SYSDATE - :1 / 1440
