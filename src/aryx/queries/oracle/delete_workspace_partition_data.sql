DELETE FROM aryx_entity_member WHERE workspace_id = %(wid)s;
DELETE FROM aryx_relationship WHERE workspace_id = %(wid)s;
DELETE FROM aryx_entity WHERE workspace_id = %(wid)s;
DELETE FROM aryx_landed_record WHERE workspace_id = %(wid)s;
