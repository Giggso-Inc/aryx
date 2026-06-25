-- Oracle ADB 23ai: delete completed jobs older than :1 days.
DELETE FROM aryx_job WHERE finished_at IS NOT NULL
  AND finished_at < SYSDATE - :1
