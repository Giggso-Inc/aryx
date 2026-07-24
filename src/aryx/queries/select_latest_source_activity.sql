SELECT source_system, source_dataset, MAX(cleaned_at) AS latest_cleaned_at
FROM aryx_landed_record
WHERE workspace_id = %s
GROUP BY source_system, source_dataset
