-- Oracle ADB 23ai: merge attribute patch into entity JSON.
-- Uses JSON_MERGEPATCH instead of PostgreSQL JSONB || operator.
-- Raw :N binds used (no %s) so the translation layer does not trigger RETURNING rewrite.
UPDATE aryx_entity
SET attributes = JSON_MERGEPATCH(attributes, :1),
    updated_at = CURRENT_TIMESTAMP
WHERE id = :2 AND workspace_id = :3
