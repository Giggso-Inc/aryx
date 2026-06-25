-- Oracle ADB 23ai: upsert run stage — PL/SQL UPDATE + conditional INSERT.
-- MERGE + USING DUAL caused DPY-4009: thin mode counts every :N occurrence as a
-- separate positional bind (12 total for 4 vars), not deduplicating by index.
-- PL/SQL blocks reuse :N correctly. Params: :1=run_id :2=stage :3=status :4=detail
BEGIN
  UPDATE aryx_run_stage
  SET status      = :3,
      detail      = :4,
      started_at  = CASE WHEN :3 = 'running' THEN CURRENT_TIMESTAMP ELSE started_at END,
      finished_at = CASE WHEN :3 IN ('done', 'failed') THEN CURRENT_TIMESTAMP ELSE NULL END
  WHERE run_id = :1 AND stage = :2;

  IF SQL%ROWCOUNT = 0 THEN
    INSERT INTO aryx_run_stage (run_id, stage, status, detail, started_at, finished_at)
    VALUES (:1, :2, :3, :4,
            CASE WHEN :3 = 'running' THEN CURRENT_TIMESTAMP ELSE NULL END,
            CASE WHEN :3 IN ('done', 'failed') THEN CURRENT_TIMESTAMP ELSE NULL END);
  END IF;
END;
