-- Oracle ADB 23ai: delete job events older than :1 days.
DELETE FROM aryx_job_event WHERE ts < SYSDATE - :1
