-- Oracle ADB 23ai: merge source entity attributes into destination (dst keys win).
-- Replaces PostgreSQL UPDATE...FROM syntax with a correlated subquery.
--
-- JSON_MERGEPATCH(target, patch) applies patch OVER target -- patch wins on
-- key conflicts, opposite of PostgreSQL's jsonb `||` (right operand wins).
-- To mirror `src.attributes || dst.attributes` (dst/survivor wins), src
-- must be the target and dst the patch -- NOT dst-as-target as an earlier
-- version of this file had it, which silently let the about-to-be-deleted
-- duplicate's values win over the confirmed survivor's (found by post-
-- merge review: silent, unrecoverable data loss on every adjudication
-- merge with a conflicting attribute key).
-- Params: :1=keep(dst.id), :2=ws(dst.workspace_id), :3=drop(src.id), :4=ws(src.workspace_id)
UPDATE aryx_entity dst
SET attributes = JSON_MERGEPATCH(
        (SELECT src.attributes FROM aryx_entity src
         WHERE src.id = :3 AND src.workspace_id = :4),
        dst.attributes
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE dst.id = :1 AND dst.workspace_id = :2
