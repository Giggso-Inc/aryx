# API Flow: POST /admin/docs/read

**Module:** `src/aryx/api/doc_discover_api.py`
**Pipeline:** `src/aryx/pipeline/doc_discovery.py`

This is Step 1 of the three-step Document Self-Discovery flow:

```
POST /admin/docs/read   →   GET /admin/docs/summary/{did}   →   POST /admin/docs/confirm
      (this document)
```

The user uploads files. Aryx reads them, runs entity extraction, and surfaces
discovered types — **without writing a single entity to the database**. The user
reviews what was found and confirms which types to keep before anything lands.

> **Key distinction:** Step 8 extracts entity *mentions* (raw, unresolved).
> Actual `aryx_entity` rows are only created later, during `POST /admin/docs/confirm`
> → `run_pipeline()` → `resolve_run()`.

---

## Complete Flow Diagram

```
CLIENT
  │
  │  POST /admin/docs/read
  │  Content-Type: multipart/form-data
  │  Body: files[]=<binary>, context="...", workspace_id=1
  │
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║  HTTP HANDLER  (doc_discover_api.py :: read)                        ║
║                                                                      ║
║  1. Read file bytes + validate 50 MB limit per file                 ║
║  2. Generate discovery_id = uuid4().hex                             ║
║  3. JobStore.create(did, "discovery", workspace_id)                 ║
║     → INSERT aryx_jobs (status=queued)                              ║
║  4. Schedule _read_job as BackgroundTask                            ║
║  5. Return {"discovery_id": "<hex>"} immediately                    ║
╚══════════════════════════════════════════════════════════════════════╝
  │  HTTP 200 {"discovery_id": "a3f9..."}  ← client receives this NOW
  │
  │  (background thread picks up)
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║  _read_job()  (background thread)                                   ║
║                                                                      ║
║  JobStore.update_stage(did, "Reading", 30, "Reading N file(s)…")   ║
║  → UPDATE aryx_jobs + INSERT aryx_job_events                        ║
║                                                                      ║
║  Split files by extension:                                          ║
║    DOC_EXTS  → write to NamedTemporaryFile → doc_paths[]           ║
║    DATA_EXTS → keep as bytes               → tabular[]             ║
╚══════════════════════════════════════════════════════════════════════╝
           │
     ┌─────┴──────┐
     │            │
     ▼            ▼
 doc_paths[]    tabular[]
 (.pdf/.docx    (.csv/.json
  /.png etc)     /.xml)
     │            │
     ▼            │
╔════════════╗   │
║ DOCUMENT   ║   │
║ PIPELINE   ║   │
║ (per file) ║   │
╚════╤═══════╝   │
     │            │
  [step 1/8]     │
  Parse pages    │
     │            │
     │  ┌─────────────────────────────────────────────────────────────┐
     │  │  EXTERNAL API CALL A: Document Parsing                      │
     │  │  OCI: OCI Document Understanding · Local: pymupdf/tesseract │
     │  └─────────────────────────────────────────────────────────────┘
     │
  [step 2/8]
  Chunk pages (chunk_pages)
  → list[DocumentChunk]
     │
  [step 3/8]
  PII screen (screen_chunks)
  → presidio-analyzer runs locally
     │
  [step 4/8]  → INSERT aryx_document
  Save document row
     │
  [step 5/8]  → INSERT aryx_chunk
  Save chunks
     │
  [step 6/8]
  Embed chunks
     │
     │  ┌─────────────────────────────────────────────────────────────┐
     │  │  EXTERNAL API CALL B: Embedding                             │
     │  │  OCI: OCI GenAI Embed · Local: Ollama /api/embed            │
     │  └─────────────────────────────────────────────────────────────┘
     │
  [step 7/8]  → INSERT aryx_chunk_embedding
  Save embeddings
     │
  [step 8/8]  ◄──── ENTITY MENTIONS EXTRACTED HERE
  extract_mentions() — LLM NER per chunk
     │
     │  ┌─────────────────────────────────────────────────────────────┐
     │  │  EXTERNAL API CALL C: LLM NER (cheap tier)                  │
     │  │  OCI: OCI GenAI Chat · Local: Ollama /api/chat              │
     │  └─────────────────────────────────────────────────────────────┘
     │
  list[RawRecord]   ← raw mentions, NOT yet entities
  payload: {type, name, span, chunk_index, ...attributes}
     │
     ▼
  (tabular path runs in parallel ───────────────────────────────────┐)
                                                                     │
     │      XML → _xml_to_csvs()  → per-element CSVs               │
     │      _infer_type() per file                                  │
     │          ┌──────────────────────────────────────────────┐    │
     │          │  EXTERNAL API CALL D: Tabular Type Inference  │    │
     │          │  Same LLM backend as C · llm_runtime.chat()   │    │
     │          └──────────────────────────────────────────────┘    │
     │      tab_plans[] {filename, ontology_type, match_keys}        │
     └───────────────────────────────────────────────────────────────┘
                               │
                               ▼
                    ╔══════════════════════╗
                    ║  Summary Assembly    ║
                    ║  mentions → types[]  ║
                    ║  tab_plans → files[] ║
                    ╚══════════╤═══════════╝
                               │
              discoveries.put(did, {mentions, tabular, summary})
              (process memory — no DB write)
                               │
              JobStore.finish(did, status="complete")
                               │
                    GET /admin/docs/summary/{did}
                    ← {"types": [...], "files": [...]}
```

---

## Document Pipeline — Step-by-Step Detail

### Pre-step: Content hash

**File:** `doc_router.py:ingest_document()`

Before any step runs:
```python
doc_id = hashlib.sha256(path.read_bytes()).hexdigest()
source = SourceRef(system="document", dataset=path.stem, record_id=doc_id)
```

- `doc_id` is a SHA-256 hex digest of the raw file bytes — used as the idempotency key in step 4.
- `SourceRef` carries provenance (system, dataset, record_id) into every chunk and mention.

---

### Step 1/8 — Parse Pages

**File:** `doc_router.py:_connector_for()` → connector's `extract_pages()`
**Log:** `[step 1/8] pages=N path=filename`

Picks the connector based on backend and file extension:

| Mode | Extension | Connector | Mechanism |
|------|-----------|-----------|-----------|
| OCI | `.pdf`, `.docx`, `.pptx`, images | `OciDocConnector` | OCI Document Understanding API (base64 inline, max 15 MB) |
| Local | `.pdf` | `PdfConnector` | pymupdf — layout-aware text extraction |
| Local | `.docx`, `.doc`, `.rtf` | `DocxConnector` | python-docx |
| Local | `.pptx`, `.ppt` | `PptxConnector` | python-pptx |
| Local | `.jpg`, `.png`, `.tiff`, `.bmp` | `ImageConnector` | pytesseract OCR |
| Local | `.html`, `.htm` | `MarkupConnector` | html.parser |

> `.xml`/`.html`/`.htm` are **not** sent to OCI Document Understanding even in OCI mode — they fall through to local `MarkupConnector`.

**Output:** `list[tuple[int, str]]` — `(page_num, raw_text)` per page/slide.

---

### Step 2/8 — Chunk Pages

**File:** `pipeline/clean_text.py:chunk_pages()`
**Log:** `[step 2/8] chunks=N doc_id=<8chars>`

Two sub-operations:

**1. Normalize** (`_normalize(text)`):
```python
text = unicodedata.normalize("NFC", text)    # canonical unicode form
text = re.sub(r"-\n(\S)", r"\1", text)       # rejoin hyphenated line-breaks
text = re.sub(r"\n{3,}", "\n\n", text)       # collapse excess blank lines
```

**2. Sliding window split:**
```
chunk_size  = ARYX_CHUNK_SIZE    (default 1000 chars)
overlap     = ARYX_CHUNK_OVERLAP (default 100 chars)

page text: [─────────────────────────────────────────]
chunk 0:   [────────────────────────]
chunk 1:              [────────────────────────]
chunk 2:                        [────────────────────]
           ←── 1000 chars ──→
                      ←── 100 overlap ──→
```

**Output per chunk:** `DocumentChunk(doc_id, chunk_index, page_slide, text, char_start, char_end, source)`

> No text leaves the machine at this step. PII screen (step 3) runs before any external call.

---

### Step 3/8 — PII Screen

**File:** `pipeline/pii.py:screen_chunks()`
**Log:** `[step 3/8] pii screening chunks=N`

Runs entirely locally — **no external call**. Uses presidio-analyzer (spaCy `en_core_web_sm` + regex recognizers).

**Default policy (`DEFAULT_POLICY`):**

| Entity type | Action | Result in text |
|------------|--------|----------------|
| `EMAIL_ADDRESS` | hash | `sha256_<hex>` |
| `PHONE_NUMBER` | mask | `<PHONE_NUMBER>` |
| `PERSON` | mask | `<PERSON>` |
| `CREDIT_CARD` | drop | *(removed)* |
| `IBAN_CODE` | drop | *(removed)* |
| `US_SSN` | drop | *(removed)* |
| Any other | mask | `<ENTITY_TYPE>` |

**Fail-closed:** if `presidio_analyzer` or `spacy en_core_web_sm` fails to load, this raises immediately. No unscreened text can proceed.

**Output:** New `list[DocumentChunk]` with anonymized `.text` fields. Chunks with no PII pass through unchanged.

---

### Step 4/8 — Save Document Row

**File:** `store/chunk_store.py:ChunkStore.upsert_document()`
**Log:** `[step 4/8] doc saved doc_db_id=N`

```python
cur.execute(load("upsert_document"),
            (content_hash, file_name, source_type, byte_count))
doc_db_id = row[0]
```

**Table:** `aryx_document`

| Column | Value |
|--------|-------|
| `content_hash` | SHA-256 hex (the `doc_id` from pre-step) |
| `file_name` | original filename |
| `source_type` | extension without dot (`pdf`, `docx`, etc.) |
| `byte_count` | file size in bytes |

**Idempotent** on `content_hash` (ON CONFLICT DO NOTHING or UPDATE). Re-uploading the same file will return the existing `doc_db_id` without creating a duplicate.

**Output:** `doc_db_id: int` — used as the FK for chunk rows in step 5.

---

### Step 5/8 — Save Chunks

**File:** `store/chunk_store.py:ChunkStore.save_chunks()`
**Log:** `[step 5/8] chunks saved ids=N`

```python
for chunk in chunks:
    cur.execute(load("insert_chunk"),
                (doc_db_id, chunk.chunk_index, chunk.page_slide,
                 chunk.char_start, chunk.char_end, chunk.text))
    ids.append(row[0])
```

**Table:** `aryx_chunk`

| Column | Value |
|--------|-------|
| `doc_id` (FK) | `doc_db_id` from step 4 |
| `chunk_index` | 0-based sequential index across the whole document |
| `page_slide` | source page or slide number |
| `char_start` / `char_end` | character offsets within the normalized page text |
| `text` | PII-anonymized chunk text |

**Output:** `list[int]` — DB-assigned chunk IDs, positionally aligned with the `chunks` list. Used in step 7 to link embeddings.

---

### Step 6/8 — Embed Chunks

**File:** `pipeline/embed.py:embed_chunks()` → `broker.embed(texts)`
**Log:** `[step 6/8] embedding chunks=N`

```python
texts = [c.text for c in chunks]   # all chunk texts sent in one batch
vectors = broker.embed(texts)
```

**Backend dispatch:**
- `ARYX_EMBED_BACKEND=local` (default) → `broker._ollama_embed()` → `POST http://ollama:11434/api/embed`
- `ARYX_EMBED_BACKEND=oci` → `broker._oci_embed()` → OCI GenAI `EmbedTextDetails`

**Dim validation (fail-closed):**
```python
if expected_dim is not None and len(vectors[0]) != expected_dim:
    raise RuntimeError("embed dim mismatch ...")
```

If the model produces a different vector dimension than `ARYX_EMBED_DIM`, the entire document fails. This prevents mixed-dim vectors from entering the store silently.

**Output:** `list[ChunkEmbedding(chunk_index, doc_id, model_id, dim, vector)]`

---

### Step 7/8 — Save Embeddings

**File:** `store/chunk_store.py:ChunkStore.save_embeddings()`
**Log:** `[step 7/8] embeddings=N saving to db`

```python
for chunk_db_id, emb in zip(chunk_db_ids, embeddings):
    vec_str = "[" + ",".join(str(v) for v in emb.vector) + "]"
    cur.execute(load("insert_chunk_embedding"),
                (chunk_db_id, emb.model_id, emb.dim, vec_str))
```

**Table:** `aryx_chunk_embedding`

| Column | Value |
|--------|-------|
| `chunk_id` (FK) | from step 5 |
| `model_id` | e.g. `nomic-embed-text` or `cohere.embed-multilingual-v3.0` |
| `dim` | vector dimension (768 local, 1024 OCI) |
| `embedding` | pgvector column — serialized as `[f1,f2,...]` |

These vectors power the RAG retrieval path (`/ask`) — once written here, semantic search over this document is live.

---

### Step 8/8 — Extract Entity Mentions

**File:** `ontology/extract.py:extract_mentions()`
**Log:** `[step 8/8] extracting mentions chunks=N`

> **This is where entity extraction happens.** One LLM call per chunk. Results are raw *mentions*, not yet resolved entities.

#### System prompt

```
[Optional workspace context prepended if set]

You extract entity mentions from document text for a domain-specific
knowledge graph. For each mention return:
(1) type   — singular PascalCase real-world concept
             (Goal, Invoice, Customer, Risk, Feature, etc.)
             Fall back to generic NER (Organization, Person, Product)
             ONLY when no domain type fits. NEVER use "Entity"/"Item".
(2) name   — exact name as it literally appears in the text
(3) attributes — typed attributes (role, founded, value, owner, etc.)
(4) span   — short verbatim excerpt containing the name word-for-word
```

#### User prompt (per chunk)
```json
{"chunk_index": 3, "text": "<PII-screened chunk text>"}
```

#### LLM response schema
```json
{
  "mentions": [
    {
      "type": "Invoice",
      "name": "INV-2024-001",
      "span": "Invoice INV-2024-001 dated January 15",
      "attributes": {"date": "2024-01-15", "amount": "$4,200"}
    }
  ]
}
```

#### Verbatim-span gate (deterministic, free)
```python
def _verbatim_ok(name: str, span: str) -> bool:
    return name.lower() in span.lower()
```

Any mention where `name` does not appear word-for-word inside `span` is **silently dropped**. This prevents hallucinated entity names from entering the knowledge graph.

#### Accepted mention → RawRecord
```python
mention_id = f"{doc_id}:{chunk_index}:{i}"
RawRecord(
    source  = SourceRef(system="document", dataset=path.stem,
                        record_id=mention_id),
    payload = {
        "type":        "Invoice",
        "name":        "INV-2024-001",
        "chunk_index": 3,
        "span":        "Invoice INV-2024-001 dated January 15",
        "date":        "2024-01-15",       # from attributes
        "amount":      "$4,200",           # from attributes
    }
)
```

**Output:** `list[RawRecord]` — one per accepted mention across all chunks.

> **These are NOT entities yet.** They are raw mentions stored in process memory (`discoveries._STORE`).
> Entity resolution (dedup/merge into `aryx_entity`) only happens after the user confirms types
> via `POST /admin/docs/confirm` → `run_pipeline()` → `resolve_run()`.

---

## Where Entities Are Actually Created

```
POST /admin/docs/read        → extracts RawRecord mentions (process memory only)
                                  ↓
GET /admin/docs/summary      → user reviews types
                                  ↓
POST /admin/docs/confirm     → ingest_confirmed()
                                  ↓
  run_pipeline(RecordsConnector(recs), ...)
                                  ↓
  discover() → lands records → aryx_landed
                                  ↓
  resolve_run() → dedup + merge → aryx_entity   ← ENTITIES WRITTEN HERE
                                  ↓
  project_graph() → FalkorDB / Oracle Graph
```

| Stage | Table written | What |
|-------|--------------|------|
| `/read` step 4 | `aryx_document` | document metadata |
| `/read` step 5 | `aryx_chunk` | text chunks |
| `/read` step 7 | `aryx_chunk_embedding` | embedding vectors |
| `/confirm` → discover | `aryx_landed` | raw records from mentions |
| `/confirm` → resolve | `aryx_entity` | **canonical entities** |
| `/confirm` → project | FalkorDB / Oracle Graph | graph nodes + edges |

---

## External APIs Called

### API Call A — Document Parsing (Step 1/8)

**Triggered when:** `ARYX_PARSE_BACKEND=oci` or `ARYX_OCI_MODE=true`
**File:** `connectors/oci_doc.py:OciDocConnector.extract_pages()`

**Request:**
```python
AnalyzeDocumentDetails(
    document       = InlineDocumentDetails(data="<base64>"),  # max 15 MB raw
    features       = [DocumentTextExtractionFeature(),
                      DocumentTableExtractionFeature()],
    compartment_id = ARYX_OCI_COMPARTMENT_ID
)
```

**Response parsed to:** `Iterator[(page_num: int, text: str)]`

**Local fallback:** pymupdf / python-docx / pytesseract — no external call.

---

### API Call B — Embedding (Step 6/8)

**File:** `broker/__init__.py:Broker.embed()`

#### Local — Ollama
```
POST http://ollama:11434/api/embed
{"model": "nomic-embed-text", "input": ["text1", "text2", ...]}
→ {"embeddings": [[0.012, ...], [0.055, ...]]}   dim=768
```

#### OCI — GenAI Embed
```python
EmbedTextDetails(inputs=[...], serving_mode=OnDemandServingMode(
    model_id="cohere.embed-multilingual-v3.0"),
    compartment_id=..., input_type="SEARCH_DOCUMENT")
→ response.data.embeddings   dim=1024
```

---

### API Call C — LLM NER (Step 8/8, per chunk)

**File:** `ontology/extract.py:extract_mentions()` → `llm.complete_json()`

#### Local — Ollama
```
POST http://ollama:11434/api/chat
{"model": "llama3.2:3b", "stream": false, "format": {mentions JSON schema},
 "messages": [{"role":"system","content":"NER prompt"},
              {"role":"user","content":"{chunk_index, text}"}]}
→ message.content = '{"mentions":[...]}'
  prompt_eval_count, eval_count (token counts)
```

#### OCI — GenAI Chat
```python
CohereChatRequest(message=chunk_json, preamble_override=system_prompt,
                  max_tokens=2048, temperature=0.2)
→ chat_response.text = '{"mentions":[...]}'
```

---

### API Call D — Tabular Type Inference (per file)

**File:** `pipeline/doc_discovery.py:_infer_type()` → `llm_runtime.chat("menial", ...)`

Same LLM backend as C. Prompt asks which columns uniquely identify each row.
```
→ {"ontology_type": "Customer", "match_keys": ["customer_id"]}
```

Filename wins if non-generic (`customers.csv` → `Customer`). LLM only invoked for generic names like `data.csv`.

---

## Which APIs Are Called — Decision Matrix

| Condition | A · Parse | B · Embed | C · NER | D · Type Infer |
|-----------|-----------|-----------|---------|----------------|
| Local mode (default) | No (local libs) | Ollama `/api/embed` | Ollama `/api/chat` | Ollama `/api/chat` |
| `ARYX_OCI_MODE=true` | OCI Doc Understanding | OCI GenAI Embed | OCI GenAI Chat | OCI GenAI Chat |
| Doc files only | Yes | Yes | Yes | **No** |
| Tabular files only | **No** | **No** | **No** | Yes |
| Both file types | Yes | Yes | Yes | Yes |

---

## Database Writes During /read

| Table | Operation | Step | Written after /confirm? |
|-------|-----------|------|------------------------|
| `aryx_jobs` | INSERT | HTTP handler | — |
| `aryx_jobs` | UPDATE | Background job start + end | — |
| `aryx_job_events` | INSERT | Each stage update | — |
| `aryx_document` | UPSERT | Step 4/8 — idempotent on hash | — |
| `aryx_chunk` | INSERT | Step 5/8 | — |
| `aryx_chunk_embedding` | INSERT | Step 7/8 — pgvector | — |
| `aryx_entity` | **Never** | Not during /read | Yes — /confirm → resolve_run() |
| `aryx_landed` | **Never** | Not during /read | Yes — /confirm → discover() |

---

## Error Paths

| Error | Where | Behaviour |
|-------|-------|-----------|
| File > 50 MB | HTTP handler | `HTTPException 400` — no job created |
| OCI file > 15 MB | Step 1/8 | `ValueError` — job marked `failed` |
| OCI Document Understanding unreachable | Step 1/8 | Exception → job `failed` |
| `presidio_analyzer` / spaCy not installed | Step 3/8 | Raises — job `failed`, no unscreened text passes |
| Ollama not running | Step 6/8 | `RuntimeError` — job `failed` |
| Embed dim mismatch | Step 6/8 | `RuntimeError` — job `failed` |
| LLM NER chunk fails | Step 8/8 | Chunk skipped, rest continue (logged at WARNING) |
| Mention fails verbatim-span gate | Step 8/8 | Mention dropped, rest continue (logged at DEBUG) |
| LLM type inference fails | `_infer_type` | Fallback to filename-derived type, never propagates |
| Process restart after /read | After job complete | `GET /summary` → `{}`, `POST /confirm` → 404 |

---

## Related Files

| File | Role |
|------|------|
| `src/aryx/api/doc_discover_api.py` | HTTP handlers — `/read`, `/summary`, `/confirm` |
| `src/aryx/pipeline/doc_discovery.py` | Core: `read_files`, `_infer_type`, `_xml_to_csvs`, `_detect_fk_links`, `ingest_confirmed` |
| `src/aryx/connectors/doc_router.py` | 8-step pipeline: `ingest_document()` |
| `src/aryx/pipeline/clean_text.py` | Step 2 — `chunk_pages()`, `_normalize()` |
| `src/aryx/pipeline/pii.py` | Step 3 — `screen_chunks()`, `DEFAULT_POLICY` |
| `src/aryx/store/chunk_store.py` | Steps 4, 5, 7 — `upsert_document`, `save_chunks`, `save_embeddings` |
| `src/aryx/pipeline/embed.py` | Step 6 — `embed_chunks()` |
| `src/aryx/ontology/extract.py` | Step 8 — `extract_mentions()`, verbatim-span gate |
| `src/aryx/connectors/oci_doc.py` | API Call A — OCI Document Understanding |
| `src/aryx/broker/__init__.py` | API Call B — embed dispatch (Ollama or OCI GenAI) |
| `src/aryx/llm_providers.py` | Ollama / OCI GenAI / Anthropic call implementations |
| `src/aryx/llm_runtime.py` | API Call D — `chat("menial", ...)` for tabular type inference |
| `src/aryx/discoveries.py` | In-process discovery result store |
| `src/aryx/store/job_store.py` | `aryx_jobs` + `aryx_job_events` persistence |

---

*Next: `doc-discover-confirm.md` — the `/confirm` flow where mentions become entities.*
