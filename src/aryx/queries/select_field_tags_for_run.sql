SELECT field, semantic_type, is_pii
  FROM aryx_field_tag
 WHERE run_id = %s
