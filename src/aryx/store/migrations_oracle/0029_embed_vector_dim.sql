-- Widen the embedding column from VECTOR(768) to VECTOR(*, FLOAT32).
-- Required for OCI GenAI Cohere Embed v3 which produces 1024-dim vectors.
-- VECTOR(*, FLOAT32) accepts any dimension so the same schema works for
-- both Ollama (768-dim) and Cohere (1024-dim) without further migrations.
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE aryx_chunk_embedding MODIFY (embedding VECTOR(*, FLOAT32))';
EXCEPTION WHEN OTHERS THEN
  -- ORA-01442: column already of the target type — safe to ignore.
  IF SQLCODE != -1442 THEN RAISE; END IF;
END;
/
