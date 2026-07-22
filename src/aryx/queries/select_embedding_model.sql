SELECT ce.dim
FROM aryx_chunk_embedding ce
JOIN aryx_chunk c ON c.id = ce.chunk_id
JOIN aryx_document d ON d.id = c.doc_id
WHERE ce.model_id = %s
LIMIT 1
