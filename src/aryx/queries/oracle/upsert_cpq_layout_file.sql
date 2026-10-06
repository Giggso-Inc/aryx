MERGE INTO aryx_cpq_layout_file t
USING dual
ON (t.workspace_id = :workspace_id AND t.catalog_prefix = :catalog_prefix AND t.variant = :variant)
WHEN MATCHED THEN
    UPDATE SET
        t.layout_id    = :layout_id,
        t.filename     = :filename,
        t.content_clob = :content_clob,
        t.status       = 'active',
        t.uploaded_at  = :uploaded_at
WHEN NOT MATCHED THEN
    INSERT (layout_id, workspace_id, catalog_prefix, variant, filename, content_clob, status, uploaded_at)
    VALUES (:layout_id, :workspace_id, :catalog_prefix, :variant, :filename, :content_clob, 'active', :uploaded_at)
