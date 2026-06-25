-- Widen the embedding column from VECTOR(768) to VECTOR(*, FLOAT32).
-- Required for OCI GenAI Cohere Embed v3 which produces 1024-dim vectors.
-- VECTOR(*, FLOAT32) accepts any dimension so the same schema works for
-- both Ollama (768-dim) and Cohere (1024-dim) without further migrations.
--
-- ORA-51859: Oracle 23ai does not support MODIFY on VECTOR columns.
-- Workaround: drop the column and re-add it with the new type.
-- Existing embeddings are lost and must be re-ingested — this is expected
-- when switching from a 768-dim model (Ollama) to 1024-dim (Cohere Embed v3).
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_chunk_embedding DROP COLUMN embedding';
EXCEPTION WHEN OTHERS THEN
  -- ORA-00904: column does not exist — already dropped, continue.
  IF SQLCODE != -904 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_chunk_embedding ADD (embedding VECTOR(*, FLOAT32))';
EXCEPTION WHEN OTHERS THEN
  -- ORA-01430: column already exists — already added, continue.
  IF SQLCODE != -1430 THEN RAISE; END IF;
END;
/
