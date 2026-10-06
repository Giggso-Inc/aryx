SELECT content_clob
FROM aryx_cpq_layout_file
WHERE workspace_id = %s
  AND catalog_prefix = %s
  AND variant = %s
  AND status = 'active'
