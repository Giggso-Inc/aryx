-- Oracle ADB 23ai: upsert run stage.
-- Replaces: INSERT ... ON CONFLICT (run_id, stage) DO UPDATE SET status/detail/timestamps
MERGE INTO aryx_run_stage t
USING (SELECT :1 AS run_id, :2 AS stage, :3 AS status, :4 AS detail FROM DUAL) s
ON (t.run_id = s.run_id AND t.stage = s.stage)
WHEN MATCHED THEN UPDATE SET
    t.status      = s.status,
    t.detail      = s.detail,
    t.started_at  = CASE WHEN s.status = 'running'
                         THEN CURRENT_TIMESTAMP ELSE t.started_at END,
    t.finished_at = CASE WHEN s.status IN ('done', 'failed')
                         THEN CURRENT_TIMESTAMP ELSE NULL END
WHEN NOT MATCHED THEN INSERT (run_id, stage, status, detail)
    VALUES (s.run_id, s.stage, s.status, s.detail)
