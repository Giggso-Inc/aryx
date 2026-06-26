-- Oracle ADB 23ai: upsert chunk embedding vector.
-- TO_VECTOR() converts the "[f1,f2,...]" string to Oracle VECTOR type.
-- ON CONFLICT kept so translation layer sets conflict_ignore for ORA-00001 swallowing.
INSERT INTO aryx_chunk_embedding (chunk_id, model_id, dim, embedding)
VALUES (:1, :2, :3, TO_VECTOR(:4))
ON CONFLICT (chunk_id, model_id) DO NOTHING
