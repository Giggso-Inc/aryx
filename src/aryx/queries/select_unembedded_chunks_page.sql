SELECT c.id, c.text
FROM aryx_chunk c
WHERE c.id > %(after_id)s
  AND NOT EXISTS (
      SELECT 1
      FROM aryx_chunk_embedding ce
      WHERE ce.chunk_id = c.id
        AND ce.model_id = %(model_id)s
  )
ORDER BY c.id
LIMIT %(batch_size)s
