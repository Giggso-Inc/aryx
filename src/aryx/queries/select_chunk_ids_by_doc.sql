SELECT id, chunk_index
FROM aryx_chunk
WHERE doc_id = %s AND chunk_index = ANY(%s)
