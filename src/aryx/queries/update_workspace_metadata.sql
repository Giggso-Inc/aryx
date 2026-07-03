UPDATE aryx_workspace
SET
    name = COALESCE(%s, name),
    description = COALESCE(%s, description)
WHERE id = %s
RETURNING id, name, description, context, brief, created_at
