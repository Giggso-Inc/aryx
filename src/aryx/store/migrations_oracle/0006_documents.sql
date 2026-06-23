-- Oracle ADB 23ai: documents + chunks + embeddings.
-- Oracle 23ai has native VECTOR type. pgvector extension not needed.

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_document (
    id           NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    content_hash VARCHAR2(4000) NOT NULL UNIQUE,
    file_name    VARCHAR2(4000) NOT NULL,
    source_type  VARCHAR2(4000) NOT NULL,
    byte_count   NUMBER(19) DEFAULT 0 NOT NULL,
    ingested_at  TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_chunk (
    id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    doc_id      NUMBER NOT NULL REFERENCES aryx_document (id),
    chunk_index NUMBER(10) NOT NULL,
    page_slide  NUMBER(10),
    char_start  NUMBER(10) DEFAULT 0 NOT NULL,
    char_end    NUMBER(10) DEFAULT 0 NOT NULL,
    text        CLOB NOT NULL,
    UNIQUE (doc_id, chunk_index)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_chunk_doc ON aryx_chunk (doc_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1408 THEN NULL; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE TABLE aryx_chunk_embedding (
    id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chunk_id    NUMBER NOT NULL REFERENCES aryx_chunk (id),
    model_id    VARCHAR2(4000) NOT NULL,
    dim         NUMBER(10) NOT NULL,
    embedding   VECTOR(768, FLOAT32),
    embedded_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    UNIQUE (chunk_id, model_id)
  )';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
