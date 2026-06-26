-- ORACLE:RETURNING id
-- Oracle ADB 23ai: insert-or-update document, return id.
-- 4 input params (:1..:4); out var appended at position :5.
DECLARE
BEGIN
    BEGIN
        INSERT INTO aryx_document (content_hash, file_name, source_type, byte_count)
        VALUES (:1, :2, :3, :4)
        RETURNING id INTO :5;
    EXCEPTION
        WHEN DUP_VAL_ON_INDEX THEN
            UPDATE aryx_document
               SET file_name = :2
             WHERE content_hash = :1
            RETURNING id INTO :5;
    END;
END;
