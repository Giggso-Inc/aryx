-- Oracle ADB 23ai: LLM call aggregate stats — workspace-scoped.
-- Replaces avg(latency_ms)::int (Postgres cast stripped by _translate_sql,
-- leaving a FLOAT) with ROUND(AVG(...)) to return an integer.
SELECT COUNT(*)                                            AS total_calls,
       COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS total_tokens,
       COALESCE(ROUND(AVG(latency_ms)), 0)                 AS avg_latency_ms,
       COALESCE(SUM(prompt_tokens), 0)                     AS prompt_tokens,
       COALESCE(SUM(completion_tokens), 0)                 AS completion_tokens
FROM   aryx_llm_call
WHERE  workspace_id = :1
