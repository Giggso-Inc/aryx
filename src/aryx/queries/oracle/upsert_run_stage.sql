-- Oracle ADB 23ai: upsert run stage.
-- oracledb thin mode assigns bind slots by ORDER OF FIRST APPEARANCE in the
-- SQL text, not by :N number. DECLARE all input vars in order :1,:2,:3 so the
-- slots match what Python passes: (run_id, stage, status, detail).
-- :4 (detail JSON) is first referenced in BEGIN where it follows :1/:2/:3.
-- Params: :1=run_id :2=stage :3=status :4=detail
DECLARE
  l_run_id  NUMBER(19)               := :1;
  l_stage   VARCHAR2(4000)           := :2;
  l_status  VARCHAR2(100)            := :3;
  l_now     TIMESTAMP WITH TIME ZONE := CURRENT_TIMESTAMP;
BEGIN
  BEGIN
    INSERT INTO aryx_run_stage (run_id, stage, status, detail, started_at, finished_at)
    VALUES (l_run_id, l_stage, l_status, :4,
            l_now,
            CASE WHEN l_status IN ('done', 'failed') THEN l_now ELSE NULL END);
  EXCEPTION
    WHEN DUP_VAL_ON_INDEX THEN
      UPDATE aryx_run_stage
         SET status      = l_status,
             detail      = :4,
             started_at  = CASE WHEN l_status = 'running' THEN l_now ELSE started_at END,
             finished_at = CASE WHEN l_status IN ('done', 'failed') THEN l_now ELSE NULL END
       WHERE run_id = l_run_id AND stage = l_stage;
  END;
END;
