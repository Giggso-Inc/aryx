-- ORACLE:RETURNING id, name, enabled, fires_count, created_at
-- Oracle ADB 23ai: insert-or-update ontology rule.
-- 5 input params (:1..:5); out vars appended at positions :6..:10.
DECLARE
BEGIN
    BEGIN
        INSERT INTO aryx_ontology_rule (workspace_id, name, when_clause, then_clause, enabled)
        VALUES (:1, :2, :3, :4, :5)
        RETURNING id, name, enabled, fires_count, created_at
            INTO :6, :7, :8, :9, :10;
    EXCEPTION
        WHEN DUP_VAL_ON_INDEX THEN
            UPDATE aryx_ontology_rule
               SET when_clause = :3,
                   then_clause = :4,
                   enabled     = :5
             WHERE workspace_id = :1 AND name = :2
            RETURNING id, name, enabled, fires_count, created_at
                INTO :6, :7, :8, :9, :10;
    END;
END;
