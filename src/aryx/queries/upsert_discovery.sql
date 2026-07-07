INSERT INTO aryx_discovery (
    discovery_id, workspace_id, status,
    data_json, summary_json, file_count, confirm_state, created_at
) VALUES (
    %(discovery_id)s, %(workspace_id)s, 'pending',
    %(data_json)s, %(summary_json)s, %(file_count)s, '{}', %(created_at)s
)
ON CONFLICT (discovery_id) DO UPDATE SET
    data_json    = EXCLUDED.data_json,
    summary_json = EXCLUDED.summary_json,
    file_count   = EXCLUDED.file_count
