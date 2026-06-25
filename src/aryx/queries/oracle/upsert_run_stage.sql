-- Oracle ADB 23ai: upsert run stage.
-- Uses USING DUAL (not a subquery) so oracledb thin mode parses :N bind vars.
-- USING (SELECT :1 FROM DUAL) is NOT used — thin mode misses binds in subqueries.
-- Params: :1=run_id, :2=stage, :3=status, :4=detail
MERGE INTO aryx_run_stage t
USING DUAL ON (t.run_id = :1 AND t.stage = :2)
WHEN MATCHED THEN UPDATE SET
    t.status      = :3,
    t.detail      = :4,
    t.started_at  = CASE WHEN :3 = 'running'
                         THEN CURRENT_TIMESTAMP ELSE t.started_at END,
    t.finished_at = CASE WHEN :3 IN ('done', 'failed')
                         THEN CURRENT_TIMESTAMP ELSE NULL END
WHEN NOT MATCHED THEN INSERT (run_id, stage, status, detail, started_at, finished_at)
    VALUES (:1, :2, :3, :4,
            CASE WHEN :3 = 'running' THEN CURRENT_TIMESTAMP ELSE NULL END,
            CASE WHEN :3 IN ('done', 'failed') THEN CURRENT_TIMESTAMP ELSE NULL END)
