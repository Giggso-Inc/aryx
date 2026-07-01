-- Oracle ADB 23ai: adjudication stats.
-- Replaces COUNT(*) FILTER (WHERE ...) with COUNT(CASE WHEN ...).
SELECT
    COUNT(CASE WHEN status = 'pending'  THEN 1 END)  AS pending,
    COUNT(CASE WHEN status = 'approved' THEN 1 END)  AS approved,
    COUNT(CASE WHEN status = 'rejected' THEN 1 END)  AS rejected,
    COUNT(CASE WHEN status = 'auto_llm' THEN 1 END)  AS auto_llm,
    COUNT(CASE WHEN status IN ('approved','rejected')
               AND llm_verdict IS NOT NULL
               AND llm_verdict = CASE WHEN status = 'approved' THEN 'Y' ELSE 'N' END
               THEN 1 END)                           AS human_llm_agree,
    COUNT(CASE WHEN status IN ('approved','rejected')
               AND llm_verdict IS NOT NULL
               THEN 1 END)                           AS human_llm_overlap
FROM aryx_adjudication
WHERE workspace_id = :1
