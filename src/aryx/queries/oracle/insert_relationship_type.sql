-- ORACLE:RETURNING id, workspace_id, name, source_type, target_type, description, created_at
-- Oracle ADB 23ai: insert-or-update relationship type.
-- Named params; out vars injected as dict keys r0..r6 (:r0..:r6).
DECLARE
BEGIN
    BEGIN
        INSERT INTO aryx_relationship_type
            (workspace_id, name, source_type, target_type, description)
        VALUES (:workspace_id, :name, :source_type, :target_type, :description)
        RETURNING id, workspace_id, name, source_type, target_type, description, created_at
            INTO :r0, :r1, :r2, :r3, :r4, :r5, :r6;
    EXCEPTION
        WHEN DUP_VAL_ON_INDEX THEN
            UPDATE aryx_relationship_type
               SET description = :description
             WHERE workspace_id = :workspace_id
               AND source_type  = :source_type
               AND name         = :name
               AND target_type  = :target_type
            RETURNING id, workspace_id, name, source_type, target_type, description, created_at
                INTO :r0, :r1, :r2, :r3, :r4, :r5, :r6;
    END;
END;
