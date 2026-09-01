-- Oracle ADB 23ai: full replace of entity attributes (matches Postgres's
-- SET attributes = %s -- entity_store.update_entity's "Replace attributes"
-- contract, NOT a merge). Named binds so the translator's RETURNING
-- rewrite fires the same way it does for %s-based generic queries.
UPDATE aryx_entity
SET attributes = %s,
    updated_at = CURRENT_TIMESTAMP
WHERE id = %s AND workspace_id = %s
RETURNING id, ontology_type, attributes
