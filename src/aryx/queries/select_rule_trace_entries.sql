SELECT seq_no, pass_num, rule_type, rule_id, attr, outcome, bml_tier, fired_at
FROM aryx_rule_trace_entry
WHERE run_id = %s
ORDER BY seq_no
