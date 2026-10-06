INSERT INTO aryx_cpq_layout_file (
    layout_id, workspace_id, catalog_prefix, variant, filename, content_clob, status, uploaded_at
) VALUES (
    %(layout_id)s, %(workspace_id)s, %(catalog_prefix)s, %(variant)s, %(filename)s, %(content_clob)s, 'active', %(uploaded_at)s
)
ON CONFLICT (workspace_id, catalog_prefix, variant) DO UPDATE SET
    layout_id    = EXCLUDED.layout_id,
    filename     = EXCLUDED.filename,
    content_clob = EXCLUDED.content_clob,
    status       = 'active',
    uploaded_at  = EXCLUDED.uploaded_at
