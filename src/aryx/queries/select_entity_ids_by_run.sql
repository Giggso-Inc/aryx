SELECT lr.source_record_id, em.entity_id
FROM aryx_landed_record lr
JOIN aryx_entity_member em ON em.landed_record_id = lr.id AND em.workspace_id = lr.workspace_id
WHERE lr.run_id = %s AND lr.workspace_id = %s
