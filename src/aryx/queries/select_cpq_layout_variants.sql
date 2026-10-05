SELECT variant
FROM aryx_cpq_layout_file
WHERE workspace_id = %s
  AND catalog_prefix = %s
  AND status = 'active'
ORDER BY uploaded_at, variant
