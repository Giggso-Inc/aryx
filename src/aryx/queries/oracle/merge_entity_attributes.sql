-- Oracle ADB 23ai: merge source entity attributes into destination (dst keys win).
-- Replaces PostgreSQL UPDATE...FROM syntax with a correlated subquery.
-- JSON_MERGEPATCH(dst, src) mirrors PostgreSQL src.attributes || dst.attributes (dst wins).
-- Params: :1=keep(dst.id), :2=ws(dst.workspace_id), :3=drop(src.id), :4=ws(src.workspace_id)
UPDATE aryx_entity dst
SET attributes = JSON_MERGEPATCH(
        dst.attributes,
        (SELECT src.attributes FROM aryx_entity src
         WHERE src.id = :3 AND src.workspace_id = :4)
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE dst.id = :1 AND dst.workspace_id = :2
