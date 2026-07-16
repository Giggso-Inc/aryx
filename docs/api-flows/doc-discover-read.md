# API Flow: POST /admin/docs/read

**Module:** `src/aryx/api/doc_discover_api.py`
**Pipeline:** `src/aryx/pipeline/doc_discovery.py`

This is Step 1 of the three-step Document Self-Discovery flow:

```
POST /admin/docs/read   →   GET /admin/docs/summary/{did}   →   POST /admin/docs/confirm
      (this document)
```

**Plain-English summary:** the user uploads one or more files (documents,
spreadsheets, or data exports) with no prior setup — they don't tell Aryx what
kind of entities to look for. Aryx reads every file, figures out what "things"
(entities) are described inside it, and shows the user a preview list of what
it found. **Nothing is written to the permanent entity database at this
stage.** The user then looks at the preview and picks which of the discovered
types they actually want to keep, which happens in the next two steps
(`/summary`, `/confirm`).

> **Key distinction:** this step (particularly its internal "step 8/8")
> extracts entity *mentions* — raw, unverified guesses about what an entity
> might be, straight from the text. Actual `aryx_entity` rows (the permanent,
> deduplicated, canonical records) are only created later, during
> `POST /admin/docs/confirm` → `run_pipeline()` → `resolve_run()`. Think of
> `/read` as "highlighting candidates with a pencil" and `/confirm` as
> "committing them to ink."

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
║  1a. Read file bytes for every uploaded file (await f.read())       ║
║  1b. Reject any single file > 50 MB → HTTPException 400, no job    ║
║      created for that request (see "why" note below)                ║
║  2. Generate discovery_id = uuid4().hex                             ║
║  3. JobStore.create(did, "discovery", "<N> file(s)", workspace_id)   ║
║     → INSERT aryx_jobs (status=queued)                              ║
║  4. Schedule _read_job as a FastAPI BackgroundTask                   ║
║     (runs AFTER the HTTP response is sent, same process)             ║
║  5. Return {"discovery_id": "<hex>"} immediately — HTTP 200          ║
╚══════════════════════════════════════════════════════════════════════╝
  │  HTTP 200 {"discovery_id": "a3f9..."}  ← client receives this NOW
  │
  │  Why return before the work is done? Reading + OCR + embedding +
  │  LLM extraction for a batch of files can take from seconds to many
  │  minutes. Making the client wait on one HTTP connection that long is
  │  fragile (timeouts, proxies dropping idle connections). Instead the
  │  client gets a ticket (discovery_id) immediately and polls
  │  GET /admin/docs/summary/{did} — or watches the job's progress via
  │  the aryx_jobs / aryx_job_events tables — until it's ready.
  │
  │  (background task picks up, same process, different thread)
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║  _read_job()  (background task)                                     ║
║                                                                      ║
║  JobStore.update_stage(did, "Reading", 30, "Reading N file(s)…")   ║
║  → UPDATE aryx_jobs + INSERT aryx_job_events                        ║
║  (this is what powers a "Reading 3 files… 30%" progress bar in the  ║
║   UI — every stage change is logged as its own event row)           ║
║                                                                      ║
║  Split the uploaded files into two buckets by file extension:        ║
║    DOC_EXTS  → write to a NamedTemporaryFile on local disk           ║
║                → doc_paths[]                                         ║
║      .pdf .pptx .ppt .docx .doc .rtf .html .htm                      ║
║      .jpg .jpeg .png .tiff .tif .bmp                                 ║
║    DATA_EXTS → kept in memory as raw bytes (no temp file needed)     ║
║                → tabular[]                                           ║
║      .json .csv .xml .xlsx                                           ║
║                                                                      ║
║  Why write DOC_EXTS to a temp file but keep DATA_EXTS as bytes?      ║
║  The document connectors (pymupdf, python-docx, OCR, etc.) expect a  ║
║  file path on disk. The tabular parsers (csv/json/xml/xlsx readers)  ║
║  all work fine directly against an in-memory byte string, so the     ║
║  extra disk round-trip is skipped for them.                          ║
╚══════════════════════════════════════════════════════════════════════╝
           │
     ┌─────┴──────┐
     │            │
     ▼            ▼
 doc_paths[]    tabular[]
 (documents &   (structured data:
  images —      .json / .csv /
  see DOC_EXTS   .xml / .xlsx —
  list above)    see DATA_EXTS)
     │            │
     ▼            │
╔════════════╗   │
║ DOCUMENT   ║   │
║ PIPELINE   ║   │
║ (per file, ║   │
║ see "why"  ║   │
║ note)      ║   │
╚════╤═══════╝   │
     │            │
  [pre-step]     │
  Content hash + provenance
  (see "Pre-step" detail below)
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
  (tabular path runs independently of the document pipeline above —────┐)
                                                                        │
     │  Step T1 — Normalize each tabular file into one or more plain   │
     │  CSVs (a "plan" per resulting CSV):                             │
     │    .csv  → _consolidate_csv_names() → same file, name columns   │
     │            merged (see "why" note in Step-by-Step Detail)       │
     │    .json → passed through as-is (no conversion needed)          │
     │    .xml  → _xml_to_csvs()  → one CSV per detected element type  │
     │            (parent→child FK column injected automatically)      │
     │    .xlsx → _xlsx_to_csvs() → one CSV per visible worksheet      │
     │            (hidden / empty / header-only sheets are skipped)     │
     │                                                                  │
     │  Step T2 — For every resulting CSV, run _infer_type() to guess  │
     │  its entity type and natural key:                                │
     │          ┌──────────────────────────────────────────────┐        │
     │          │  EXTERNAL API CALL D: Tabular Type Inference  │        │
     │          │  Same LLM backend as C · llm_runtime.chat()   │        │
     │          │  (only called when the filename itself is too │        │
     │          │   generic to guess the type from, e.g.        │        │
     │          │   "data.csv" — see Step T2 detail below)       │        │
     │          └──────────────────────────────────────────────┘        │
     │      → tab_plans[] {filename, data, ontology_type, match_keys}   │
     └────────────────────────────────────────────────────────────────┘
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
- This pre-step only runs for `doc_paths[]` (documents/images). Tabular files
  (`.csv`/`.json`/`.xml`/`.xlsx`) never get a content hash — they go straight
  into the separate tabular path described in "Tabular Path — Step-by-Step
  Detail" further down.

---

### Pipeline-level: per-document timeout and worker concurrency

**File:** `connectors/doc_router.py` — `_ingest_with_timeout()`, `DocumentRouterConnector.extract()`

Two settings govern *how* the 8 steps below run across a batch of documents —
they sit outside the numbered steps because they wrap the whole per-file
pipeline, not any single step:

| Setting | Env var | Default | What it does |
|---------|---------|---------|---------------|
| Per-document timeout | `ARYX_PER_DOC_TIMEOUT` | `7200` seconds (2 hours) | Each document's full 8-step pipeline runs on its own worker thread with a hard wall-clock budget. If parsing, OCR, embedding, or extraction hangs (e.g. a stuck OCR call or an unresponsive Ollama instance) past this limit, that one document is abandoned — logged as an error — and the rest of the batch keeps going. |
| Doc worker concurrency | `ARYX_DOC_WORKERS` | `1` (sequential) | How many documents are processed *at the same time*. Default is 1 because a local CPU-bound Ollama instance gains nothing from parallel requests — they just queue up and add overhead. Raise this to 3–5 only when the LLM tiers are backed by a cloud provider (e.g. Anthropic, OCI GenAI) that can genuinely serve concurrent requests. |

**Why this matters for a new engineer:** if a batch upload of 20 PDFs seems
"stuck," check these two settings first — a single bad file can silently eat
up to 2 hours before the timeout kicks in and the batch moves on, and if
`ARYX_DOC_WORKERS=1` (the default), every file waits for the previous one to
finish or time out before it even starts.

---

### Step 1/8 — Parse Pages

**File:** `doc_router.py:_connector_for()` → connector's `extract_pages()`
**Log:** `[step 1/8] pages=N path=filename`

Picks the connector based on backend and file extension:

| Mode | Extension | Connector | Mechanism |
|------|-----------|-----------|-----------|
| OCI | `.pdf`, `.docx`, `.doc`, `.rtf`, `.pptx`, `.ppt`, images | `OciDocConnector` | OCI Document Understanding API (base64 inline, max 15 MB — see Error Paths) |
| Local | `.pdf` | `PdfConnector` | pymupdf — layout-aware text extraction |
| Local | `.docx`, `.doc`, `.rtf` | `DocxConnector` | python-docx |
| Local | `.pptx`, `.ppt` | `PptxConnector` | python-pptx |
| Local | `.jpg`, `.jpeg`, `.png`, `.tiff`, `.tif`, `.bmp` | `ImageConnector` | pytesseract OCR |
| Local | `.html`, `.htm` | `MarkupConnector` | html.parser |

> `.xml`/`.html`/`.htm` are **not** sent to OCI Document Understanding even in OCI mode — they fall through to local `MarkupConnector`. (Note: `.xml` files reaching this table would only happen if someone forced one through the document path; in the normal `/read` flow, `.xml` is treated as a *tabular* file — see the Tabular Path section — and never reaches `doc_router.py` at all.)

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

**Why hash emails but mask everything else?** An email address is often used
downstream as a *join key* (the same customer shows up in multiple
documents) — hashing it consistently lets the system still recognize "same
person" without ever storing or sending the real address to an LLM. Names,
phone numbers, and other PII don't need that join-key property, so they're
simply replaced with a generic placeholder. Credit cards, IBANs, and SSNs are
dropped outright — there's no legitimate use for keeping even a hashed trace
of those in a knowledge graph.

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

**Why idempotent on content hash?** Users often re-upload the same file by
mistake (or upload it again in a later batch that also touches other files).
Keying on a hash of the actual bytes — rather than the filename — means "the
same file" is recognized even if it was renamed, and re-running `/read` on it
never creates a second copy of the document row or duplicate chunks.

**Connection handling:** `ChunkStore` (and `JobStore`) don't open a new
database connection per call. They borrow one from a shared connection pool
(`aryx.store.pool.get_pool(dsn)`) and return it when the `with` block exits.
This matters because a batch `/read` can fire many of these calls in quick
succession across background threads — without a pool, each call opening its
own Postgres connection could exhaust the database's connection limit under
load. `ChunkStore.close()` / `JobStore.close()` are now no-ops for the same
reason — the pool, not the caller, owns the connection lifecycle.

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

## Tabular Path — Step-by-Step Detail

This path runs **independently of** the 8-step document pipeline above and
only processes files matched by `DATA_EXTS = {".json", ".csv", ".xml",
".xlsx"}`. Nothing here touches OCR, chunking, PII screening, or embeddings —
tabular data is already structured, so the job is simpler: work out what
*kind* of record each row represents, and split any file that actually
contains several different kinds of records (a multi-sheet workbook, a
nested XML export) into one clean CSV per record type.

### Step T1 — Normalize each file into one or more CSVs

**File:** `pipeline/doc_discovery.py:read_files()` (dispatch) → per-extension helper

| Extension | Helper | What happens |
|-----------|--------|----------------|
| `.csv` | `_consolidate_csv_names()` | Passed through as-is, *except* multi-part name columns (e.g. `COMPANY_NAME`, `COMPANY_NAME_2` … `COMPANY_NAME_5`) are merged into one `name` column. |
| `.json` | *(none)* | Passed through unchanged — one plan, one entity type. |
| `.xml` | `_xml_to_csvs()` | Parses the XML tree and emits one CSV per detected entity element type. |
| `.xlsx` | `_xlsx_to_csvs()` | Emits one CSV per visible worksheet. |

**Why merge multi-part name columns?** Some government/defense data exports
split a long organization name across several columns because of a legacy
fixed-width limit (`COMPANY_NAME`, `COMPANY_NAME_2`, …). Without this step,
the knowledge graph would end up with a truncated, wrong name for that
entity. `_consolidate_csv_names()` detects the `_2`/`_3`/… suffix pattern,
joins the parts back together with spaces, and writes the result into a
`name` column. It's a no-op when there's nothing to merge, so it's always
safe to run on every `.csv` upload.

#### `.xml` → `_xml_to_csvs()` in detail

- An XML element is treated as an "entity" (a candidate row) when it has
  **2 or more distinct child element types**, or — for simple leaf elements —
  at least one XML attribute (e.g. `<Widget id="1" name="alpha"/>`). Plain
  scalar values like `<id>123</id>` are **not** entities; they become fields
  on their parent instead.
- Multilingual fields (`<name><en>...</en><de>...</de></name>`) are collapsed
  to a single value — English preferred, otherwise the first non-empty
  language found.
- Every child row gets a `{parent_tag}_id` column injected automatically so
  the later `/confirm` step can wire parent → child relationships without
  any manual configuration.
- **Caps, and why they exist:** a real-world XML export (e.g. a CPQ or ERP
  system dump) can contain dozens of element types and tens of thousands of
  rows per type. Without a limit, one upload could generate an unreasonable
  number of CSVs and rows — mostly noise. Two independent caps guard against
  this:
  - `ARYX_XML_MAX_ENTITY_TYPES` (default **20**) — at most this many distinct
    element types become CSVs. Element types with a human-readable "name"
    field are preferred over anonymous ones when deciding which ones make
    the cut.
  - `ARYX_XML_MAX_ROWS_PER_TYPE` (default **500**) — each resulting CSV is
    truncated to this many rows.
- If the XML can't be parsed, or no entity-like elements are found at all,
  the raw bytes are passed through as a single fallback CSV instead of
  failing the upload outright.

#### `.xlsx` → `_xlsx_to_csvs()` in detail — multi-sheet Excel ingestion

> **This is new.** Multi-sheet Excel ingestion did not exist as a step in
> earlier versions of this endpoint — `.xlsx` was not in `DATA_EXTS` at all
> and would have been silently rejected as an unrecognized extension.

- Every **visible** worksheet in the uploaded workbook becomes its own CSV —
  mirroring the shape of `_xml_to_csvs()` so the rest of the pipeline (type
  inference, FK detection, ingestion) doesn't need a separate code path for
  spreadsheets.
- Three kinds of worksheets are deliberately **skipped**, so they never turn
  into a garbage dataset:
  - hidden or "very hidden" sheets (`sheet_state != "visible"`),
  - sheets with no header row at all (completely empty sheet),
  - sheets that have a header row but zero data rows underneath it (e.g. a
    blank "Template" tab shipped alongside the real data tabs).
- **Naming:** each output CSV is named `"{workbook_stem}__{sheet_slug}.csv"`
  — e.g. uploading `orders.xlsx` with sheets "Customers" and "Order Items!"
  produces `orders__Customers.csv` and `orders__Order_Items.csv`. The shared
  `{workbook_stem}__` prefix is what lets a later lookup recover "every sheet
  that came from this one workbook upload."
- Reads the workbook with `openpyxl` in read-only, streaming mode so large
  spreadsheets don't need to be loaded fully into memory.

**Output of Step T1:** a list of `(csv_bytes, csv_filename)` pairs. For
`.xml`/`.xlsx` uploads this can be many pairs from a single uploaded file;
for `.csv`/`.json` it is always exactly one.

---

### Step T2 — Infer entity type + natural key per CSV

**File:** `pipeline/doc_discovery.py:_infer_type()`

Runs once for every CSV produced by Step T1 (so a 5-sheet `.xlsx` upload
runs this step 5 times, once per sheet):

1. **Try the filename first.** `support_tickets.csv` → `SupportTicket`,
   `customers.csv` → `Customer`. Filenames from real-world exports are
   usually a reliable, free signal — no LLM call needed.
2. **Fall back to the LLM only when the filename is too generic** to guess
   a type from (`data.csv`, `export.csv`, `report.csv`, and similar generic
   words defined in code: `table`, `row`, `record`, `data`, `file`,
   `entity`, `item`, `object`, `dataset`, `export`, `import`, `report`,
   `sheet`, `upload`, `dump`, `output`, `input`, `sample`, `test`).
3. Either way, also determine the **natural key** column(s) — the column(s)
   that uniquely identify a row (e.g. `customer_id`). A header-suffix
   heuristic runs first (looking for `_code`, `_id`, `_key`, `_num`, `_ref`,
   `_no`, `_cage` suffixes); the LLM is only consulted when that heuristic
   and the filename both fail to produce a confident answer.

**External API Call D** (below) is what fires in step 2 above.

**Why trust the filename over the LLM?** A real export filename
(`customers.csv`, `invoices.csv`) is a stronger *and free* signal than asking
an LLM to guess from a 600-byte sample of rows — trusting it first avoids an
LLM round-trip (latency + cost) for the common case.

**If the LLM call fails for any reason** (timeout, malformed JSON response,
model unavailable), `_infer_type()` never raises — it silently falls back to
the filename-derived guess, or a generic `"Entity"` type if even the
filename was unusable. A tabular upload can never fail outright because of
this step.

**Output:** `tab_plans[]` — one dict per CSV:
`{filename, data, ontology_type, match_keys}` — plus `source_filename` /
`source_bytes` for CSVs that came from an `.xml` or `.xlsx` file, so
`/confirm` can trace a generated CSV back to the original uploaded workbook
or XML document.

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

### API Call D — Tabular Type Inference (per CSV, only for generic filenames)

**File:** `pipeline/doc_discovery.py:_infer_type()` → `llm_runtime.chat("menial", system, user)`

Prompt asks which columns uniquely identify each row.
```
→ {"ontology_type": "Customer", "match_keys": ["customer_id"]}
```

Filename wins if non-generic (`customers.csv` → `Customer`). LLM only invoked for generic names like `data.csv`.

**"Same LLM backend as C" — but plumbed differently.** Both API Call C
(entity extraction, step 8/8) and API Call D end up talking to the same
underlying tier (`"cheap"`) and the same wire protocol (Ollama `/api/chat`
locally, OCI GenAI Chat in OCI mode) — but they get there through two
different code paths:
- Call C goes through the shared application `Broker` (built once via
  `_local_broker()` in `admin_api.py`) and `aryx.llm.complete_json()`.
- Call D goes through `aryx.llm_runtime.chat("menial", ...)`, which builds
  its **own** single-model `Broker` on the fly from the live Settings-panel
  configuration (`menial_model`), then calls `aryx.llm.complete_text()`.

In practice this means: changing the "menial" model in the Settings UI
changes which model handles tabular type inference (Call D) without
touching the model that handles document entity extraction (Call C), and
vice versa — they are configured independently even though today they
usually point at the same tier.

---

## Which APIs Are Called — Decision Matrix

| Condition | A · Parse | B · Embed | C · NER | D · Type Infer |
|-----------|-----------|-----------|---------|----------------|
| Local mode (default) | No (local libs) | Ollama `/api/embed` | Ollama `/api/chat` | Ollama `/api/chat` |
| `ARYX_OCI_MODE=true` | OCI Doc Understanding | OCI GenAI Embed | OCI GenAI Chat | OCI GenAI Chat |
| Doc files only (DOC_EXTS) | Yes | Yes | Yes | **No** |
| Tabular files only (DATA_EXTS) | **No** | **No** | **No** | Only if filename is generic (see Step T2) |
| Both file types in one upload | Yes | Yes | Yes | Only for the generic-named tabular files |

> D is conditional even when tabular files are present — a well-named CSV
> (`customers.csv`) never triggers an LLM call at all.

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
| Any single file > 50 MB | HTTP handler | `HTTPException 400` — no job is created, whole request rejected before any file is processed |
| Per-document timeout exceeded (`ARYX_PER_DOC_TIMEOUT`, default 2h) | Wraps steps 1–8 | That one document is abandoned (logged as error); the rest of the batch continues |
| OCI file > 15 MB | Step 1/8 (OCI mode only) | `ValueError` — job marked `failed` |
| OCI Document Understanding unreachable | Step 1/8 (OCI mode only) | Exception → job `failed` |
| `presidio_analyzer` / spaCy not installed | Step 3/8 | Raises — job `failed`, no unscreened text passes |
| Ollama not running / no embed model configured | Step 6/8 | `RuntimeError` — job `failed` |
| Embed dim mismatch | Step 6/8 | `RuntimeError` — job `failed` |
| LLM NER chunk fails (API Call C) | Step 8/8 | That chunk is skipped, rest continue (logged at WARNING) |
| Mention fails verbatim-span gate | Step 8/8 | Mention dropped, rest continue (logged at DEBUG) |
| XML fails to parse / no entity elements found | Step T1 (`.xml`) | Falls back to a single raw-upload CSV instead of failing |
| LLM type inference fails (API Call D) | Step T2 (`_infer_type`) | Falls back to the filename-derived type — never propagates, never fails the upload |
| Discovery expired / process restarted after `/read` completed | `discoveries._STORE` (in-memory) | `GET /summary/{did}` → `{}` · `POST /confirm` → `HTTPException 404` |

> **Note on process restarts:** because `discoveries._STORE` is a plain
> in-process Python dict (see `discoveries.py`), a server restart, redeploy,
> or crash between `/read` finishing and the user calling `/confirm` loses
> the discovered mentions entirely — even though `aryx_document`,
> `aryx_chunk`, and `aryx_chunk_embedding` rows from `/read` remain in the
> database. The user would need to re-upload and re-run `/read` to get a new
> `discovery_id`.

---

## Related Files

| File | Role |
|------|------|
| `src/aryx/api/doc_discover_api.py` | HTTP handlers — `/read`, `/summary`, `/confirm` |
| `src/aryx/pipeline/doc_discovery.py` | Core: `read_files`, `_infer_type`, `_consolidate_csv_names`, `_xml_to_csvs`, `_xlsx_to_csvs`, `_detect_fk_links`, `ingest_confirmed` |
| `src/aryx/connectors/doc_router.py` | 8-step document pipeline (`ingest_document()`), per-document timeout (`ARYX_PER_DOC_TIMEOUT`) and worker concurrency (`ARYX_DOC_WORKERS`) |
| `src/aryx/pipeline/clean_text.py` | Step 2 — `chunk_pages()`, `_normalize()` |
| `src/aryx/pipeline/pii.py` | Step 3 — `screen_chunks()`, `DEFAULT_POLICY` |
| `src/aryx/store/chunk_store.py` | Steps 4, 5, 7 — `upsert_document`, `save_chunks`, `save_embeddings`; connections borrowed from the shared pool |
| `src/aryx/pipeline/embed.py` | Step 6 — `embed_chunks()` |
| `src/aryx/ontology/extract.py` | Step 8 — `extract_mentions()`, verbatim-span gate |
| `src/aryx/connectors/oci_doc.py` | API Call A — OCI Document Understanding |
| `src/aryx/broker/__init__.py` | API Call B — embed dispatch (Ollama or OCI GenAI) |
| `src/aryx/llm_providers.py` | Ollama / OCI GenAI / Anthropic call implementations |
| `src/aryx/llm_runtime.py` | API Call D — `chat("menial", ...)` for tabular type inference (its own independently-configured single-model broker) |
| `src/aryx/discoveries.py` | In-process discovery result store (`_STORE` dict — lost on process restart) |
| `src/aryx/store/job_store.py` | `aryx_jobs` + `aryx_job_events` persistence; connections borrowed from the shared pool (`src/aryx/store/pool.py`) |
| `src/aryx/config.py` | All `ARYX_*` env-var defaults referenced throughout this document |

---

*Next: `doc-discover-confirm.md` — the `/confirm` flow where mentions become entities.*

---

## Audit Note — Drift Found and Fixed in This Revision

This document was checked against the current code
(`src/aryx/api/doc_discover_api.py`, `src/aryx/pipeline/doc_discovery.py`,
`src/aryx/connectors/doc_router.py`, `src/aryx/store/job_store.py`,
`src/aryx/store/chunk_store.py`, `src/aryx/config.py`, and their direct
dependents) as of this revision. The following gaps between the previous
version of this document and the current code were found and corrected:

1. **Missing `.xlsx` support entirely.** `DATA_EXTS` in
   `pipeline/doc_discovery.py` now includes `.xlsx`, and a whole new helper
   (`_xlsx_to_csvs()`) turns a multi-sheet Excel workbook into one CSV per
   visible worksheet. The previous revision of this document never
   mentioned `.xlsx` anywhere — it would have described such an upload as
   unsupported. Added as a full new subsection under "Tabular Path —
   Step-by-Step Detail," plus updated every extension list that previously
   said `.csv/.json/.xml`.
2. **Missing CSV name-consolidation step.** `_consolidate_csv_names()` (run
   on every plain `.csv` upload to merge split `COMPANY_NAME_2`-style
   columns into `name`) was not documented at all. Added as Step T1 for
   `.csv` files, with a "why" note.
3. **Wrong XML entity-type cap.** The previous document (in the companion
   HTML file) claimed XML files are split into "one CSV per **top-3
   most-frequent** element type." The code actually caps at
   `ARYX_XML_MAX_ENTITY_TYPES` (default **20**, preferring named types) and
   additionally caps each type at `ARYX_XML_MAX_ROWS_PER_TYPE` (default
   **500**) rows. Corrected in both files.
4. **Incomplete `JobStore.create()` call signature.** The diagram showed
   `JobStore.create(did, "discovery", workspace_id)` — three arguments. The
   actual signature is `create(job_id, system, dataset, workspace_id=1)`
   (four positional values; the handler passes a human-readable dataset
   description like `"3 file(s)"`). Corrected in the diagram.
5. **No mention of per-document timeout or worker concurrency.**
   `connectors/doc_router.py` wraps each document's 8-step pipeline in a
   hard wall-clock timeout (`ARYX_PER_DOC_TIMEOUT`, default 2 hours) and
   supports running multiple documents concurrently
   (`ARYX_DOC_WORKERS`, default 1 = sequential). Neither existed in this
   document before. Added as a new "Pipeline-level" subsection plus an
   Error Paths row.
6. **No mention of shared connection pooling.** `ChunkStore` and `JobStore`
   now borrow connections from a shared pool (`store/pool.py`) instead of
   opening a new database connection per call, and their `.close()` methods
   are no-ops as a result. Added a short note under Step 4/8.
7. **`_infer_type()` / API Call D plumbing clarified.** The previous
   document said Call D uses "the same LLM backend as C" without
   qualification. In the current code they resolve to the same tier
   (`"cheap"`) but through two independently-configured code paths (the
   shared application broker for C vs. a per-call Settings-panel-driven
   broker via `llm_runtime.chat("menial", ...)` for D) — clarified so a
   future config change to one doesn't get assumed to affect the other.
8. **General granularity pass.** Broke several dense steps (file
   splitting, tabular normalization, type inference) into smaller labeled
   sub-steps, and added plain-English "why" notes throughout (PII
   hash-vs-mask choice, idempotent document upsert, filename-first type
   inference, XML/XLSX caps) so a new engineer can follow the flow without
   first reading the source.

No other functional drift was found — the 8-step document pipeline (parse →
chunk → PII screen → save document → save chunks → embed → save embeddings →
extract mentions), its external API call shapes (A–C), the verbatim-span
gate, the PII policy table, and the entity-creation boundary at `/confirm`
all still match the current code exactly.
