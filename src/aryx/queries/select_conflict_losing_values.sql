SELECT entity_id, losing_values
FROM aryx_attribute_conflict
WHERE workspace_id = %s AND attribute = %s
