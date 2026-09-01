UPDATE aryx_rule_trace_session
SET status = %s,
    sealed_at = now()
WHERE run_id = %s AND status = 'open'
