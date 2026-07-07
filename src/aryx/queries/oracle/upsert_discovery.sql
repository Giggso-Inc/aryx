MERGE INTO aryx_discovery t
USING dual
ON (t.discovery_id = :discovery_id)
WHEN MATCHED THEN
    UPDATE SET
        t.data_json    = :data_json,
        t.summary_json = :summary_json,
        t.file_count   = :file_count
WHEN NOT MATCHED THEN
    INSERT (discovery_id, workspace_id, status, data_json, summary_json, file_count, confirm_state, created_at)
    VALUES (:discovery_id, :workspace_id, 'pending', :data_json, :summary_json, :file_count, '{}', :created_at)
