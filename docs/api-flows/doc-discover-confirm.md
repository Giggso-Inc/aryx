# API Flow: POST /admin/docs/confirm

**Module:** `src/aryx/api/doc_discover_api.py`
**Core:** `src/aryx/pipeline/doc_discovery.py:ingest_confirmed()`
**Pipeline:** `src/aryx/pipeline/orchestrate.py:run_pipeline()`

This is Step 3 of the three-step Document Self-Discovery flow:

```
POST /admin/docs/read   →   GET /admin/docs/summary/{did}   →   POST /admin/docs/confirm
                                                                       (this document)
```

The user has reviewed discovered types and file plans from `/summary`. This call
ingests only what they approved — nothing that wasn't explicitly confirmed reaches
`aryx_entity` or the graph.

> **Key distinction:** `/read` wrote raw infrastructure (aryx_document, aryx_chunk,
> aryx_chunk_embedding) and extracted mentions into process memory. `/confirm` now
> pulls those mentions through the full entity resolution funnel and projects the
> result to the graph.

---

## Complete Flow Diagram

```
CLIENT
  │
  │  POST /admin/docs/confirm
  │  Content-Type: application/json
  │  Body: {
  │    "discovery_id": "a3f9...",
  │    "approved_types": ["Invoice", "Customer"],
  │    "approved_files": ["customers.csv"]
  │  }
  │
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║  HTTP HANDLER  (doc_discover_api.py :: confirm)                     ║
║                                                                      ║
║  1. discoveries.get(did) → 404 if expired or missing               ║
║  2. job_id = uuid4().hex                                            ║
║  3. JobStore.create(job_id, "documents", "confirmed entities",      ║
║                     workspace_id)                                    ║
║     → INSERT aryx_jobs (status=queued)                              ║
║  4. Schedule _confirm_job as BackgroundTask                         ║
║  5. Return {"status": "queued", "job_id": "<hex>"} immediately      ║
╚══════════════════════════════════════════════════════════════════════╝
  │  HTTP 200 {"status": "queued", "job_id": "b7c2..."}
  │
  │  (background thread picks up)
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║  _confirm_job()  (background thread)                                ║
║                                                                      ║
║  data = discoveries.get(did)                                        ║
║    → ValueError if expired (process memory gone on restart)        ║
║                                                                      ║
║  ingest_confirmed(data, approved_types, approved_files,             ║
║                   broker, jobs, job_id, workspace_id)               ║
╚══════════════════════════════════════════════════════════════════════╝
           │
           │  loops over approved_types then approved_files
           │
     ┌─────┴─────────────────────────────────┐
     │  For each approved_type               │  For each approved_file
     │  (document entity mentions)           │  (tabular data)
     │                                       │
     ▼                                       ▼
╔═══════════════════╗              ╔═══════════════════════╗
║  Filter mentions  ║              ║  _detect_fk_links()   ║
║  by type          ║              ║  → auto FK detection  ║
║  recs = mentions  ║              ║    across all plans   ║
║  where type==X    ║              ║                       ║
╚═════════╤═════════╝              ║  For each file:       ║
          │                        ║  CsvConnector or      ║
          │                        ║  JsonConnector        ║
          ▼                        ╚══════════╤════════════╝
  RecordsConnector(recs)                      │
          │                                   │
          └──────────────┬────────────────────┘
                         │
                         ▼
          ╔══════════════════════════════╗
          ║  run_pipeline()             ║
          ║  orchestrate.py             ║
          ╚══════════════╤══════════════╝
                         │
                    [stage 1/5]
                    Discover
                    → aryx_runs + aryx_landed
                         │
                    [stage 2/5]
                    Resolve
                    → block → score → route → cluster
                    → aryx_entity + aryx_entity_member
                         │
                    [stage 3/5]
                    Relate (relate=True)
                    → LLM relationship inference
                    → aryx_relationship
                         │
                    [stage 4/5]
                    FK Link (last file only)
                    → pattern match across plans
                    → aryx_relationship
                         │
                    [stage 5/5]
                    Project
                    → FalkorDB / Oracle Graph
```

---

## Pipeline Stages — Step-by-Step Detail

### Pre-pipeline: Data retrieval

**File:** `doc_discover_api.py:_confirm_job()`

```python
data = discoveries.get(did)
```

Retrieves the full discovery result stored in process memory by `/read`:
```python
{
  "mentions": [RawRecord, ...],   # extracted by step 8/8 of /read
  "tabular":  [{filename, data, ontology_type, match_keys}, ...],
  "summary":  {...},
  "workspace_id": 1
}
```

If `data` is `None` (process restart, TTL expiry, or wrong `discovery_id`):
→ raises `ValueError("discovery expired — re-read the files")` → job marked `failed`.

---

### For each approved_type — RawRecord path

**File:** `doc_discovery.py:ingest_confirmed()`

```python
recs = [m for m in data["mentions"] if m.payload.get("type") == otype]
```

Filters the full mention list to only those whose `payload["type"]` matches the approved type. If no mentions exist for a type (user approved a type but it appears in zero chunks), `recs` is empty and `run_pipeline` is called with an empty connector — producing zero entities, no error.

**Connector:** `RecordsConnector(recs)` — wraps the list of `RawRecord` objects as an iterable source.

**Pipeline call:**
```python
run_pipeline(
    connector=RecordsConnector(recs),
    dsn=settings.rdb_dsn,
    system="document",
    dataset=otype,         # e.g. "Invoice"
    ontology_type=otype,
    match_keys=["name"],   # entity identity key for resolution
    graph_url=settings.graph_url,
    broker=broker,
    relate=True,           # LLM relationship inference enabled
    workspace_id=workspace_id,
)
```

---

### For each approved_file — Tabular path

**File:** `doc_discovery.py:ingest_confirmed()`

**FK detection (runs once across all approved files):**
```python
valid_plans = [plans matching approved_files, in approval order]
auto_fk = _detect_fk_links(valid_plans)
```

`_detect_fk_links()` scans column headers looking for `{TypeB}_id` or `{TypeB}_name` patterns:
```
customers.csv has column: order_id    → no FK (order_id is not "{TypeB}_id" for any B)
orders.csv    has column: customer_id → FK: orders.customer_id → customers.id
→ auto_fk = [{source_type:"Order", source_attr:"customer_id",
               target_type:"Customer", target_attr:"id",
               name:"CUSTOMER_HAS_ORDER"}]
```

FK links are passed only to the **last** file's `run_pipeline` call — all prior entities must exist before cross-file linking can match.

**Connector selection:**
- `.json` → `JsonConnector(tmp_path, system="json")`
- `.csv`, `.xml`-expanded → `CsvConnector(data_bytes, system="csv", dataset=stem)`

**Pipeline call (last file gets fk_links):**
```python
run_pipeline(
    connector=conn,
    dsn=settings.rdb_dsn,
    system=Path(fname).suffix.lstrip("."),   # "csv", "json"
    dataset=Path(fname).stem,                # filename stem
    ontology_type=plan["ontology_type"],     # e.g. "Customer"
    match_keys=plan["match_keys"],           # e.g. ["customer_id"]
    relate=True,
    fk_links=auto_fk if is_last else None,
    workspace_id=workspace_id,
)
```

---

### Stage 1/5 — Discover

**File:** `discover.py:discover()` → `pipeline/run.py:run_spine()`

```python
run_id = store.start_run(system, dataset)
```

**Table:** `aryx_runs`

| Column | Value |
|--------|-------|
| `system` | "document" or file extension |
| `dataset` | ontology_type or filename stem |
| `status` | "running" |

Returns `run_id: int`.

```python
profiles = run_spine(connector, sink=BatchSink(store, run_id))
```

`run_spine()` iterates the connector and for each record:
1. Cleans (normalise whitespace, strip nulls)
2. Profiles (infer field types: string/numeric/date/boolean)
3. Calls `sink.land(record)` → batched INSERT into `aryx_landed`

**Table:** `aryx_landed`

| Column | Value |
|--------|-------|
| `run_id` (FK) | run_id from above |
| `workspace_id` | workspace_id |
| `source_system` | e.g. "document" |
| `payload` | JSONB — full record payload |
| `cleaned_at` | timestamp |

```python
store.save_profiles(run_id, profiles)
```

**Table:** `aryx_profile_columns` — field name, inferred type, null rate, cardinality per column.

```python
store.finish_run(run_id, sink.total)
```

UPDATE `aryx_runs` → status="complete", record_count=N.

> For the document path (`tag=False`): no LLM field tagging runs. For tabular files, `tag=False` here too — tagging is opt-in via the `/ingest/file` path.

**Output:** `run_id: int` — used by all downstream stages.

---

### Stage 2/5 — Resolve (Entity Resolution Funnel)

**File:** `resolve_entities.py:resolve_run()` → `resolution/run.py:resolve()`

```python
records = store.landed_records(run_id, key_attrs)
```

Reads `aryx_landed WHERE run_id=? AND workspace_id=?`. For each row, builds the **match text** used for deduplication:
```python
text = " ".join(str(payload.get(a, "")) for a in key_attrs).strip()
# match_keys=["name"] → text = "INV-2024-001"
# match_keys=["customer_id", "email"] → text = "C001 alice@acme.com"
```

#### Resolution funnel — 4 sub-stages

**4a. Blocking**

`block(records)` — groups records into candidate blocks to avoid O(n²) pairwise comparison across the whole dataset:
- 4-char prefix of match text
- Token-set canonical form (sorted tokens)
- Soundex of first token

Records only compete within the same block.

**4b. Embedding (per block)**

`_block_embeddings(group, broker)` — embeds match texts for cosine similarity:
- Skipped entirely when `er_auto_merge >= 1.0 AND er_adjudicate >= 1.0` (exact-match-only mode)
- Runs in batches of `ARYX_EMBED_BATCH_SIZE`
- Falls back silently to string-only scoring if embed fails for a batch

External API: Ollama `/api/embed` or OCI GenAI Embed (same as `/read` step 6/8).

**4c. Scoring**

`score_pair(left.text, right.text, vec_left, vec_right)` — combined score:
- String similarity: token-set ratio + Jaro-Winkler
- Cosine similarity (when embeddings available)
- Weighted combination → score ∈ [0.0, 1.0]

**4d. Four-way threshold routing**

| Score range | Action | Threshold env var |
|-------------|--------|-------------------|
| ≥ 0.92 | Auto-merge → `union.union(left, right)` | `ARYX_ER_AUTO_MERGE` |
| [0.90, 0.92) | LLM adjudicate → merge if same, queue if LLM down | `ARYX_ER_ADJUDICATE` |
| [0.75, 0.90) | Human queue → INSERT `aryx_adjudication` (status=pending) | `ARYX_ER_REVIEW` |
| < 0.75 | Auto-reject — no action, no DB write | — |

**LLM adjudication** (score in [0.90, 0.92)) — `adjudicate(left, right, broker)`:
- Frontier tier — calls `broker.chat("frontier", system_prompt, user)`
- User prompt: both record payloads as JSON
- Returns bool: same entity or not
- If LLM unavailable → pair queued for human (conservative: wrong merge > missed merge)

External API: Ollama `/api/chat` or OCI GenAI Chat at frontier tier.

#### Clustering and golden record

After all pairs are routed, `UnionFind.groups()` produces clusters of merged record IDs.

For each cluster:
```python
_materialize(member_ids, by_id, pair_scores, ontology_type, policy)
```

Builds the golden record via **confidence-weighted merge**:
- For each attribute: the value from the highest-confidence member wins
- Conflicting values → logged to `aryx_attribute_conflict`
- `cluster_confidence(edges, n_members)` → entity-level confidence score

#### Persistence

`store.save(results)` — for each `(ResolvedEntity, members)`:

**Table: `aryx_entity`**

| Column | Value |
|--------|-------|
| `workspace_id` | workspace |
| `ontology_type` | e.g. "Invoice" |
| `attributes` | JSONB — merged golden record |
| `confidence` | float [0.0, 1.0] |

**Table: `aryx_entity_member`**

| Column | Value |
|--------|-------|
| `entity_id` (FK) | the resolved entity |
| `landed_record_id` (FK) | a contributing `aryx_landed` row |
| `confidence` | member contribution confidence |

**Table: `aryx_attribute_conflict`** (when merge produced conflicts)

| Column | Value |
|--------|-------|
| `entity_id` | the resolved entity |
| `attribute` | conflicting field name |
| `winning_value` | JSONB — the value that won |
| `losing_values` | JSONB array — all other values |
| `strategy` | "highest_confidence" or policy name |

**Table: `aryx_adjudication`** (pairs in review band)

| Column | Value |
|--------|-------|
| `left_record_id` / `right_record_id` | the pair |
| `score` | similarity score |
| `llm_verdict` | bool or None if LLM unavailable |
| `status` | "pending" or "auto_llm" |

**Ontology type seeding (idempotent):**
```python
OntologyStore.seed_types([OntologyType(name=ontology_type, status="approved", source="pipeline")])
```
→ INSERT INTO `aryx_ontology_type` ON CONFLICT DO NOTHING — ensures the type appears in the Browse tab immediately.

---

### Stage 3/5 — Relate (LLM Relationship Inference)

**File:** `pipeline/enrich.py:_relate()`
**Triggered when:** `relate=True` (always in `/confirm` path)

For each pair of entities (up to `ARYX_MAX_RELATE_PAIRS`), the LLM infers whether a meaningful relationship exists and names it.

**External API:** Ollama `/api/chat` or OCI GenAI Chat at frontier tier.

**Table: `aryx_relationship`**

| Column | Value |
|--------|-------|
| `workspace_id` | workspace |
| `source_entity_id` (FK) | from `aryx_entity` |
| `target_entity_id` (FK) | from `aryx_entity` |
| `name` | e.g. "INVOICE_BELONGS_TO_CUSTOMER" |
| `confidence` | float |

---

### Stage 4/5 — FK Link (cross-file join, last file only)

**File:** `pipeline/fk_edges.py:link_by_attribute()`
**Triggered when:** `fk_links` is non-None (last approved file only)

For each FK spec from `_detect_fk_links()`:
- Reads `aryx_entity` for `source_type` and `target_type`
- Matches on `source_attr` value == `target_attr` value (exact string match)
- Inserts a directional relationship for each matched pair

```python
link_by_attribute(
    estore,
    source_type="Order",        # the entity that carries the FK
    source_attr="customer_id",  # the FK column
    target_type="Customer",     # the entity being referenced
    target_attr="id",           # the PK or match key
    name="CUSTOMER_HAS_ORDER",  # edge label
)
```

**Table:** `aryx_relationship` (same as stage 3)

> No LLM call at this stage — deterministic pattern matching only.

---

### Stage 5/5 — Project to Graph

**File:** `project.py:project_graph()`

Selects graph backend from `settings.effective_graph_backend()`:
- `"falkordb"` → `FalkorStore(graph_url, ws_graph(workspace_id))`
- `"oci_graph"` → `OracleGraphStore(settings.oci_adb_dsn, workspace_id)`

Reads from `aryx_entity` + `aryx_relationship`, writes nodes and edges:

**FalkorDB:**
- `MERGE (n:TypeName {entity_id: X}) SET n += attributes`
- `MERGE (a)-[:RELATIONSHIP_NAME]->(b)`

**Oracle Graph (ADB 23ai):**
- `INSERT INTO {workspace}_vertices ...`
- `INSERT INTO {workspace}_edges ...`

Also calls `_build_type_ancestors(dsn)` to fold parent type labels onto each node (so `Invoice` nodes also carry their parent type `Document` if so configured in `aryx_ontology_type`).

**Returns:**
```python
{"run_id": N, "entities": N, "relationships": N, "nodes_written": N, "edges_written": N}
```

---

## External APIs Called

### API A — Embedding (Stage 2/5 — per block)

Same backends as `/read` step 6/8.

**Triggered:** during `_block_embeddings()` inside the resolve funnel — once per block per `run_pipeline` call.

**Request:** same as `/read` API Call B — batch of match texts.

**Skipped when:** `ARYX_ER_AUTO_MERGE >= 1.0 AND ARYX_ER_ADJUDICATE >= 1.0` (exact-match-only mode).

---

### API B — LLM Adjudication (Stage 2/5 — per pair in [0.90, 0.92) band)

**File:** `resolution/adjudicate.py:adjudicate()`
**Tier:** frontier (highest quality)

```
POST http://ollama:11434/api/chat
{
  "model": "llama3.2:70b",     ← frontier tier
  "messages": [
    {"role": "system", "content": "Are these the same entity?"},
    {"role": "user", "content":
      "{\"left\": {payload A}, \"right\": {payload B}}"}
  ]
}
→ bool: true = same entity, false = different
```

OCI equivalent: `CohereChatRequest` at `command-r-plus` tier.

**Conservative fallback:** if LLM unavailable or times out, pair goes to human queue (`aryx_adjudication`), not auto-merged.

---

### API C — Relationship Inference (Stage 3/5 — relate)

**File:** `pipeline/enrich.py:_relate()`
**Tier:** frontier

For each candidate entity pair:
```
{"role": "user", "content":
  "{\"entity_a\": {attrs}, \"entity_b\": {attrs}}
   Is there a meaningful named relationship between these?"}
→ {"has_relationship": true, "name": "INVOICE_ISSUED_BY", "confidence": 0.87}
```

Capped by `ARYX_MAX_RELATE_PAIRS` (default 100).

---

## Decision Matrix — Which APIs Are Called

| Condition | A · Embed | B · Adjudicate | C · Relate |
|-----------|-----------|----------------|------------|
| Document types (always) | Yes (per block) | Only in [0.90,0.92) | Yes (relate=True) |
| Tabular files (always) | Yes (per block) | Only in [0.90,0.92) | Yes (relate=True) |
| `er_auto_merge=1.0 AND er_adjudicate=1.0` | No (skip embed) | No | Yes |
| Zero mentions for approved type | No (empty connector) | No | No |
| `fk_links` present (last file) | No extra call | No extra call | No extra call |
| Local mode | Ollama /api/embed | Ollama /api/chat | Ollama /api/chat |
| `ARYX_OCI_MODE=true` | OCI GenAI Embed | OCI GenAI Chat | OCI GenAI Chat |

---

## Database Writes During /confirm

| Table | Operation | Stage | Notes |
|-------|-----------|-------|-------|
| `aryx_jobs` | INSERT | HTTP handler | type="documents" |
| `aryx_jobs` | UPDATE | Per-type/file progress + finish | |
| `aryx_job_events` | INSERT | Each stage update | |
| `aryx_runs` | INSERT | Stage 1 — start_run | one per run_pipeline call |
| `aryx_landed` | INSERT | Stage 1 — sink.land() | batched, one per record |
| `aryx_profile_columns` | INSERT | Stage 1 — save_profiles | field stats |
| `aryx_runs` | UPDATE | Stage 1 — finish_run | record_count |
| `aryx_entity` | INSERT | Stage 2 — save() | canonical entities |
| `aryx_entity_member` | INSERT | Stage 2 — save() | provenance links |
| `aryx_attribute_conflict` | INSERT | Stage 2 — save() | merge conflicts only |
| `aryx_adjudication` | INSERT | Stage 2 — review band | human queue items |
| `aryx_ontology_type` | INSERT (idempotent) | After stage 2 | seed_types ON CONFLICT DO NOTHING |
| `aryx_relationship` | INSERT | Stage 3 (LLM relate) + Stage 4 (FK link) | |
| FalkorDB / Oracle Graph | MERGE/INSERT | Stage 5 — project_graph | nodes + edges |

---

## Error Paths

| Error | Where | Behaviour |
|-------|-------|-----------|
| `discovery_id` not found | HTTP handler | HTTPException 404 |
| `discoveries.get(did)` returns None | `_confirm_job` | ValueError → job marked failed |
| Process restart between /read and /confirm | `_confirm_job` | ValueError "discovery expired" — re-run /read |
| Empty mention list for approved type | `ingest_confirmed` | `run_pipeline` called with empty connector — zero entities, no error |
| `aryx_runs` INSERT fails | Stage 1 | Exception → job failed for this type/file |
| Embed unavailable for a batch | Stage 2 blocking | Silent fallback to string-only scoring for that batch |
| LLM adjudication unavailable | Stage 2 threshold | Pair queued for human (`aryx_adjudication` status=pending) |
| Relate LLM unavailable | Stage 3 | Exception propagates → job failed (relate is not optional-fail-safe) |
| FK link finds no matches | Stage 4 | No writes, continues silently |
| FalkorDB unreachable | Stage 5 | Exception → job failed |
| Oracle Graph unavailable | Stage 5 | Exception → job failed |

---

## How This Connects to /read

```
/read  →  aryx_document    (step 4/8)
       →  aryx_chunk        (step 5/8)
       →  aryx_chunk_embedding  (step 7/8)
       →  discoveries._STORE[did]  (mentions in process memory)

/confirm  →  aryx_runs          (stage 1 — one per type/file)
          →  aryx_landed        (stage 1 — one per mention/row)
          →  aryx_entity        (stage 2 — canonical entities)  ← ENTITIES CREATED HERE
          →  aryx_entity_member (stage 2 — provenance)
          →  aryx_adjudication  (stage 2 — human queue items)
          →  aryx_relationship  (stages 3+4 — graph edges)
          →  FalkorDB / Oracle Graph  (stage 5)
```

The `/read` infrastructure writes (aryx_document, aryx_chunk, aryx_chunk_embedding)
persist regardless of whether `/confirm` is ever called. They power `/ask` RAG
retrieval independently of the entity resolution path.

---

## Related Files

| File | Role |
|------|------|
| `src/aryx/api/doc_discover_api.py` | HTTP handlers — `/read`, `/summary`, `/confirm` |
| `src/aryx/pipeline/doc_discovery.py` | `ingest_confirmed()`, `_detect_fk_links()` |
| `src/aryx/pipeline/orchestrate.py` | `run_pipeline()` — stages 1–5 |
| `src/aryx/discover.py` | Stage 1 — `discover()` → `run_spine()` → land records |
| `src/aryx/pipeline/run.py` | `run_spine()` — extract + clean + profile + batch-land |
| `src/aryx/resolve_entities.py` | Stage 2 entry — `resolve_run()` |
| `src/aryx/resolution/run.py` | Resolution funnel — block + score + route + cluster |
| `src/aryx/resolution/classical.py` | `block()`, `score_pair()` |
| `src/aryx/resolution/adjudicate.py` | LLM adjudication — `adjudicate()` |
| `src/aryx/resolution/cluster.py` | `UnionFind`, `golden_record_weighted()` |
| `src/aryx/resolution/golden.py` | `golden_record_with_policy()` |
| `src/aryx/pipeline/enrich.py` | Stage 3 — `_relate()`, `_build_type_ancestors()` |
| `src/aryx/pipeline/fk_edges.py` | Stage 4 — `link_by_attribute()` |
| `src/aryx/project.py` | Stage 5 — `project_graph()` |
| `src/aryx/store/entity_store.py` | `save()`, `landed_records()`, `save_relationships()` |
| `src/aryx/store/postgres_store.py` | `start_run()`, `finish_run()`, `save_profiles()` |
| `src/aryx/store/batch_sink.py` | Batched `aryx_landed` INSERT |
| `src/aryx/store/ontology_store.py` | `seed_types()` — idempotent type registration |
| `src/aryx/discoveries.py` | In-process discovery result store (put/get/expire) |
| `src/aryx/graph/oracle_graph_store.py` | Oracle Graph writer (OCI mode) |
| `src/aryx/graph/__init__.py` | FalkorDB writer (local mode) |

---

*Previous: `doc-discover-read.md` — the `/read` flow that populates the discovery store.*
