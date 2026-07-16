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

> **Key distinction (in plain English):** `/read` only *looked* at the uploaded
> files — it split them into chunks, embedded them, and pulled out candidate
> "mentions" (things that look like entities), but it kept all of that in
> memory/staging tables. Nothing became a real, queryable entity yet.
> `/confirm` is where the user's approvals get acted on: only the entity
> types and files the user actually checked off get pushed through entity
> resolution (dedup + merge) and written into the graph. If the user never
> calls `/confirm`, none of that downstream data exists — `/read`'s writes
> (`aryx_document`, `aryx_chunk`, `aryx_chunk_embedding`) still exist and are
> useful for `/ask` search, but there is no `aryx_entity` row and nothing in
> the graph.

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
  │    "approved_files": ["customers.csv", "workbook__Orders.csv"]
  │  }                          ▲
  │                             └─ note: for a multi-sheet Excel upload or a
  │                                multi-entity XML upload, /read already split
  │                                it into several derived per-sheet / per-entity
  │                                CSV "files" — approved_files must name those
  │                                derived files, not the original .xlsx/.xml name.
  ▼
╔══════════════════════════════════════════════════════════════════════╗
║  HTTP HANDLER  (doc_discover_api.py :: confirm)                     ║
║                                                                      ║
║  1. discoveries.get(did) → 404 if expired or missing                ║
║  2. job_id = uuid4().hex                                            ║
║  3. JobStore.create(job_id, "documents", "confirmed entities",      ║
║                     workspace_id)                                    ║
║     → INSERT aryx_jobs (status=queued)                              ║
║  4. Schedule _confirm_job as BackgroundTask                          ║
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
║    → ValueError if expired (process memory gone on restart)         ║
║                                                                      ║
║  ingest_confirmed(data, approved_types, approved_files,             ║
║                   broker, jobs, job_id, workspace_id)                ║
╚══════════════════════════════════════════════════════════════════════╝
           │
           │  runs approved_types to completion FIRST, one at a time,
           │  THEN moves on to approved_files
           │
     ┌─────┴─────────────────────────────────┐
     │  1) For each approved_type,           │  2) For all approved_files together
     │     one after another                 │     (files run mostly in parallel)
     │  (document entity mentions)           │
     │                                       │
     ▼                                       ▼
╔═══════════════════╗              ╔═══════════════════════════════════════╗
║  Filter mentions  ║              ║  a. _detect_fk_links(valid_plans)     ║
║  by type          ║              ║     → in-batch FK detection (3 passes)║
║  recs = mentions  ║              ║  b. _detect_fk_links_workspace(...)   ║
║  where type==X    ║              ║     → FK links to types already in   ║
║                    ║              ║       the workspace from earlier runs║
╚═════════╤═════════╝              ║  c. _persist_xml_sources(...)         ║
          │                        ║     → save original XML/XLSX bytes    ║
          │                        ║       + derived-file list for provenance║
          ▼                        ║  d. Non-last files: CsvConnector or   ║
  RecordsConnector(recs,           ║     JsonConnector, run in PARALLEL    ║
  label=otype)                     ║     (skip_graph=True, relate=False)   ║
          │                        ║  e. Last file: runs AFTER all others  ║
          │                        ║     finish, SERIALLY (fk_links=auto,  ║
          │                        ║     relate=only if ARYX_INGEST_RELATE,║
          │                        ║     skip_graph=False)                 ║
          │                        ╚══════════╤═════════════════════════╝
          │                                   │
          └──────────────┬────────────────────┘
                         │   each type / each file gets its OWN
                         │   independent call to run_pipeline() below
                         ▼
          ╔══════════════════════════════╗
          ║  run_pipeline()             ║
          ║  orchestrate.py             ║
          ╚══════════════╤══════════════╝
                         │
                    [stage 1/5] Discover
                    → aryx_runs + aryx_landed + aryx_profile_columns
                         │
                    [stage 2/5] Resolve
                    → block → score → route → cluster → golden record
                    → aryx_entity + aryx_entity_member
                    → (idempotent) seed aryx_ontology_type
                         │
                    [stage 3/5] Relate   (only if relate=True for this call)
                    → sampled-pair LLM relationship inference
                    → PLUS one schema-wide LLM pass for FK-shaped columns
                    → aryx_relationship
                         │
                    [stage 4/5] FK Link   (only if fk_links was passed in)
                    → deterministic column-value pattern match
                    → aryx_relationship
                    → PLUS: relate-isolated safety net always runs here,
                      regardless of the relate flag, to avoid orphan nodes
                         │
                    [stage 5/5] Project   (skipped when skip_graph=True)
                    → FalkorDB / Oracle Graph
                         │
                         ▼
          (after ALL types + files are done)
          Zero-loss validation — read-only, best-effort, log-only.
          Never fails the job even if checks fail.
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
  "tabular":  [{filename, data, ontology_type, match_keys, ...}, ...],
  "summary":  {...},
  "workspace_id": 1
}
```

**In plain English:** think of `discoveries.get(did)` as opening a scratchpad
that `/read` left behind under a ticket number (`discovery_id`). That
scratchpad only exists in the web server's RAM — it was never written to a
database table. If the server process restarts (deploy, crash, autoscale)
between `/read` and `/confirm`, the scratchpad is gone.

If `data` is `None` (process restart, TTL expiry, or wrong `discovery_id`):
→ raises `ValueError("discovery expired — re-read the files")` → job marked `failed`.

---

### Where the "files" in `approved_files` actually come from

**File:** `doc_discovery.py:read_files()`, `_xml_to_csvs()`, `_xlsx_to_csvs()`

This matters because `/confirm` matches `approved_files` against the
**`tabular` plans that `/read` already built** — and for two upload types,
`/read` does not keep the original file as one plan. It expands it into
several derived CSV plans first:

- **Multi-sheet Excel workbooks (`.xlsx`)** — `_xlsx_to_csvs()` turns one
  workbook into one CSV per **visible** worksheet that has both a header row
  and at least one data row. Hidden sheets, fully empty sheets, and
  header-only template sheets are silently skipped (never ingested as
  garbage). Each derived plan is named
  `"{workbook_stem}__{sheet_slug}.csv"` — e.g. an uploaded
  `sales_data.xlsx` with sheets "Orders" and "Q1 Customers" becomes two
  plans: `sales_data__Orders.csv` and `sales_data__Q1_Customers.csv`. The
  shared `sales_data__` prefix is what lets you later find every sheet that
  came from the same original upload.
- **Multi-entity XML (`.xml`)** — `_xml_to_csvs()` walks the XML tree and
  turns each *repeated element type with ≥2 distinct child fields* (or a
  leaf element with attributes) into its own CSV, named
  `"{stem}_{ElementType}.csv"`. Unlike XLSX sheets, XML-derived rows get a
  synthetic `{parent_tag}_id` column injected automatically so that
  parent → child relationships can be found later without the user doing
  anything.
- **Plain `.csv` and `.json`** — used as-is (CSV additionally goes through
  `_consolidate_csv_names()`, which merges split "COMPANY_NAME" /
  "COMPANY_NAME_2" style columns into one `name` field — a `/read`-time
  detail, not a `/confirm`-time one, mentioned here only for completeness).

**Why this matters for `/confirm`:** the `GET /admin/docs/summary/{did}` response
lists these *derived* filenames, not the original upload name. The
`approved_files` array the client sends to `/confirm` must contain the
derived names shown in `/summary` (e.g. `sales_data__Orders.csv`), or that
sheet/entity type will simply be skipped — `ingest_confirmed()` looks each
name up with a plain equality match against `data["tabular"]` and silently
drops any name it can't find.

Every derived plan — one per worksheet or per XML entity type — then flows
through the **exact same tabular path** described below, completely
independently of how many sibling plans came from the same original upload.

---

### For each approved_type — RawRecord path

**File:** `doc_discovery.py:ingest_confirmed()`

Approved types are processed **one at a time, in order** (not in parallel —
parallelism is only used for tabular files, see below).

```python
recs = [m for m in data["mentions"] if m.payload.get("type") == otype]
```

Filters the full mention list to only those whose `payload["type"]` matches the approved type. If no mentions exist for a type (user approved a type but it appears in zero chunks), `recs` is empty and `run_pipeline` is called with an empty connector — producing zero entities, no error.

**Connector:** `RecordsConnector(recs, label=otype)` — wraps the list of `RawRecord` objects as an iterable source. `label=otype` is only used for logging/traceability, not for resolution logic.

**Pipeline call:**
```python
run_pipeline(
    connector=RecordsConnector(recs, label=otype), dsn=settings.rdb_dsn,
    system="document", dataset=otype, ontology_type=otype,
    match_keys=["name"],   # entity identity key for resolution
    graph_url=settings.graph_url, broker=broker,
    workspace_id=workspace_id, relate=True,   # always on for the type path
    on_progress=_progress_otype,
)
```

> **Why this matters:** `skip_graph` is **not** passed here, so it defaults
> to `False` — every approved type gets its own full graph projection
> (Stage 5) immediately after it resolves, *before* the next type even
> starts. If you approve three document types in one request, the graph
> gets rebuilt from the full `aryx_entity` table three times in a row (once
> per type), not once at the end. This is safe (the rebuild always reads the
> *entire* entity table, so the final graph is still correct) but it is
> more work than the tabular-files path does — see below, where only the
> **last** file triggers a graph write.

---

### For each approved_file — Tabular path

**File:** `doc_discovery.py:ingest_confirmed()`

#### Step 1 — Collect the plans the user actually approved, in approval order

```python
valid_plans = [plans matching approved_files, in approval order]
```

Looks each name in `approved_files` up against `data["tabular"]` (the plans
`/read` built — including any derived XLSX-sheet / XML-entity plans, see
above). Names that don't match anything are silently dropped.

#### Step 2 — Persist source provenance (new — not previously documented)

```python
_persist_xml_sources(valid_plans, workspace_id, settings.rdb_dsn)
```

For any plan that came from an XML or XLSX expansion (it carries
`source_filename` + `source_bytes` — the *original* uploaded workbook/XML,
not the derived CSV), this groups all derived plans back under their shared
original filename and calls `upsert_xml_catalog_entry()` to save the
original bytes plus the list of derived assets to the source catalog. This
is what lets the UI later say "this Customer entity type came from sheet
'Orders' inside `sales_data.xlsx`" instead of just "from a CSV". Plain
`.csv`/`.json` uploads have no `source_filename`, so this step is a no-op
for them.

#### Step 3 — FK detection, two passes

**Pass A — within this batch of approved files:**
```python
auto_fk = _detect_fk_links(valid_plans, log_id=job_id)
```

`_detect_fk_links()` compares every pair of approved files' column headers
looking for foreign-key-shaped columns, using three independent detection
rules:

- **Rule 1 — naming pattern:** a column named `{TypeB}_id` or `{TypeB}_name`
  (singular or plural, case-insensitive) in file A, where `TypeB` matches
  another approved file's ontology type. Example:
  ```
  customers.csv has column: order_id    → no FK (order_id is not "{TypeB}_id" for any B)
  orders.csv    has column: customer_id → FK: orders.customer_id → customers.id
  → auto_fk = [{source_type:"Order", source_attr:"customer_id",
                 target_type:"Customer", target_attr:"id",
                 name:"CUSTOMER_HAS_ORDER"}]
  ```
- **Rule 2 — shared-suffix code columns:** three sub-rules that catch
  code-keyed joins that don't follow the `{Type}_id` naming convention at
  all (e.g. a column literally named the same as another file's match key,
  or a column whose name *contains* another file's match-key stem). Columns
  that only ever hold one constant value across a sample of rows are
  skipped — a constant column can't be a real per-row foreign key, only a
  cartesian-product false match.
- **Rule 3 — XML element-type FK:** specific to XML-derived plans — looks
  for the synthetic `{parent_tag}_id` column that `_xml_to_csvs()` injected
  and matches it back to the plan whose `_element_type` equals that tag.

FK links are only ever applied by the **last** approved file's
`run_pipeline` call — all prior files' entities must already exist in
`aryx_entity` before a cross-file link can find anything to match.

**Pass B — against types already in the workspace (new — not previously
documented):**
```python
workspace_fk = _detect_fk_links_workspace(valid_plans[-1], known_types, ...)
```

Pass A only finds links *between files in this one `/confirm` call*. If the
user approves a single file today that references a `Customer` type
ingested last week, Pass A has nothing to compare against and returns
nothing for that column. Pass B fixes this: it reads every ontology type
already registered in `OntologyStore` for this workspace, and checks the
**last** approved file's headers against the same `{KnownType}_id` /
`{KnownType}_name` naming pattern used in Pass A Rule 1. Any match found
here is appended to `auto_fk` alongside Pass A's results.

#### Step 4 — Run each file through the pipeline, with different rules for the last file

**Connector selection:**
- `.json` → `JsonConnector(tmp_path, system="json")`
- everything else (`.csv`, and anything expanded from `.xml`/`.xlsx` into
  CSV bytes at `/read` time) → `CsvConnector(data_bytes, system="csv", dataset=stem)`

**Non-last files run in parallel; the last file runs alone, afterward:**

```python
non_last = valid_plans[:-1]
last = valid_plans[-1] if valid_plans else None
```

- All files **except the last** are submitted to a
  `ThreadPoolExecutor(max_workers=settings.ingest_workers)` (default **3**
  concurrent workers, `ARYX_INGEST_WORKERS`) and run genuinely at the same
  time.
- The **last** approved file always runs **serially, after every non-last
  file has finished** (success or failure).

> **Why split it this way?** Two independent reasons:
> 1. **FK links need everything else to exist first.** `fk_links` is only
>    ever handed to the last file's `run_pipeline` call, so it's the only
>    call that can actually match a foreign key against another file's
>    entities.
> 2. **Graph projection is not safe to run concurrently.** Projecting to
>    FalkorDB (`project_graph()`) clears the graph and rebuilds it from the
>    *entire* `aryx_entity` table. Two of those running at once would race
>    and corrupt each other. So every non-last file passes `skip_graph=True`
>    (it resolves entities into Postgres but does **not** touch the graph),
>    and only the final, serial file actually writes to FalkorDB/Oracle
>    Graph.

**Non-last file failures do not fail the job.** If a non-last file's
`run_pipeline` call raises, the exception is caught, logged, and the
filename is added to a `failed` list — the remaining files (including the
last one) still run. The job only fails outright if the **last** file's
call raises, or if some earlier, unhandled exception occurs.

**Relate is off by default for tabular files — unlike the document-type
path above.** Only the last file's call can run relate, and only if the
`ARYX_INGEST_RELATE` setting is turned on (**default: `False`**):

```python
run_pipeline(
    connector=conn,                             # JsonConnector or CsvConnector
    dsn=settings.rdb_dsn,
    system=Path(fname).suffix.lstrip("."),       # "csv", "json"
    dataset=Path(fname).stem,                    # filename stem
    ontology_type=plan["ontology_type"],         # e.g. "Customer"
    match_keys=plan["match_keys"],               # e.g. ["customer_id"]
    graph_url=settings.graph_url, broker=broker, workspace_id=workspace_id,
    fk_links=auto_fk if is_last else None,       # only the last file gets FK specs
    relate=is_last and settings.ingest_relate,   # off unless ARYX_INGEST_RELATE=true
    skip_graph=not is_last,                      # only the last file projects
    on_progress=_progress_plan,
)
```

> **Why is relate disabled by default for tabular files?** Some uploads
> (e.g. CPQ configuration exports) carry very large text fields (function
> bodies, long scripts). Sending those to the LLM for relationship
> inference can cause the call to hang. It is safe to leave relate off for
> tabular data because Stage 4's FK Link pass and the always-on
> "relate-isolated" safety net (see below) already give most tabular
> entities a path into the graph without needing an LLM call per pair.

#### Step 5 — Post-ingest validation (new — not previously documented)

**File:** `pipeline/ingest_validation.py:ground_truth_from_tabular()`, `validate_workspace()`

After every approved type and every approved file has finished (or failed
and been skipped), if there were any tabular files at all:

```python
gt = ground_truth_from_tabular(valid_plans)
report = validate_workspace(workspace_id, gt, settings.rdb_dsn, settings.graph_url)
```

This re-derives "what *should* be true" directly from the CSV bytes that
were actually ingested (row counts, id columns and their values, FK column
→ parent relationships) and runs **seven categories of read-only checks**
against the database and the graph — e.g. "did every landed row make it
into `aryx_landed`?", "does every FK column value resolve to a real parent
id, or is it dangling?", "does the graph have the node/edge counts we'd
expect?". Results and any failures are only **logged** (`logger.info` /
`logger.warning`) — this step never raises and never fails the job, even if
every check fails. Think of it as a smoke alarm, not a circuit breaker: it
tells you after the fact if something silently went wrong, it does not stop
the ingest.

---

## Inside `run_pipeline()` — What Actually Runs Per Type / Per File

Every approved type and every approved file gets its **own, independent**
call into `run_pipeline()` (`orchestrate.py`). The stages below describe
what one such call does. This is more granular than the previous version of
this document, which described 5 stages — the current pipeline has two
extra sub-steps that were added since (Schema FK Inference and the
Relate-Isolated safety net), both folded into the numbering below rather
than given their own top-level stage number, to match how the pipeline
actually groups its progress events.

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

**Resilience note (new):** `run_pipeline()` accepts an optional
`resume_run_id`. If a process crashes mid-run, a later call can pass the
same `run_id` back in; `StageRunner`/`StageTracker` (`store/checkpoint_store.py`)
read a per-stage status row and skip any stage already marked `"done"`,
redoing anything left `"running"` (a leftover `"running"` status means the
process died mid-stage). `/confirm` itself does not currently pass
`resume_run_id` — every approved type/file always starts a fresh run — but
the underlying pipeline supports resuming, which matters for understanding
`aryx_run_stage`-style checkpoint rows you may see in the database.

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

#### 2.0 — Exact-ID fast path (new — not previously documented)

Before any fuzzy scoring happens, `resolve_run()` checks:

```python
exact_ids = (settings.er_exact_id_match and bool(key_attrs)
             and all(k.lower() in {"id", "uuid", "guid", "key"} for k in key_attrs))
```

`ARYX_ER_EXACT_ID_MATCH` defaults to **`True`**. When every match key is
literally one of `id`/`uuid`/`guid`/`key` (which `doc_discovery.py`'s
`_id_priority_mk()` will promote to the match key whenever a CSV has an
explicit PK column — see the `/read` documentation), resolution skips
blocking, embedding, and scoring entirely and instead groups records by
**exact string equality** of the normalised match text
(`resolution/run.py:_resolve_exact()`).

**Why:** fuzzy string similarity is the wrong tool for opaque identifiers.
Two sequential ids like `18722401146` and `18722401147` score above 0.90 on
plain string similarity, and because merging is transitive (`A~B`, `B~C` ⇒
`A,B,C` merged), a whole range of unrelated ids can collapse into one
"entity" if similarity scoring were applied to them. Exact-ID mode also
deliberately does **not** merge two records that both have an empty match
text — fuzzy scoring treats `"" == ""` as a perfect 1.0 match, which would
otherwise silently merge every record missing the match-key attribute into
one giant entity.

When `exact_ids` is `False` (the normal case for things like
`match_keys=["name"]` or `["customer_id", "email"]`), the four-stage funnel
below runs as before.

#### 2a. Blocking

`block(records)` — groups records into candidate blocks to avoid O(n²) pairwise comparison across the whole dataset:
- 4-char prefix of match text
- Token-set canonical form (sorted tokens)
- Soundex of first token

Records only compete within the same block.

#### 2b. Embedding (per block)

`_block_embeddings(group, broker)` — embeds match texts for cosine similarity:
- Skipped entirely when `er_auto_merge >= 1.0 AND er_adjudicate >= 1.0` (exact-match-only mode)
- Runs in batches of `ARYX_EMBED_BATCH_SIZE` (default **50**)
- Falls back silently to string-only scoring if embed fails for a batch
- Capped to the first `⌈√(2 × max_pairs_per_block)⌉+2` records in the block — records the pair loop below could never reach anyway don't need a vector

External API: Ollama `/api/embed` or OCI GenAI Embed (same as `/read` step 6/8).

#### 2c. Scoring

`score_pair(left.text, right.text, vec_left, vec_right)` — combined score:
- String similarity: token-set ratio + Jaro-Winkler
- Cosine similarity (when embeddings available)
- Weighted combination → score ∈ [0.0, 1.0]

#### 2d. Four-way threshold routing

| Score range | Action | Threshold env var (default) |
|-------------|--------|-------------------|
| ≥ 0.92 | Auto-merge → `union.union(left, right)` | `ARYX_ER_AUTO_MERGE` (0.92) |
| [0.90, 0.92) | LLM adjudicate → merge if same, queue if LLM down | `ARYX_ER_ADJUDICATE` (0.90) |
| [0.75, 0.90) | Human queue → INSERT `aryx_adjudication` (status=pending) | `ARYX_ER_REVIEW` (0.75) |
| < 0.75 | Auto-reject — no action, no DB write | — |

**LLM adjudication** (score in [0.90, 0.92)) — `adjudicate(left, right, broker)`:
- Frontier tier — calls `broker.chat("frontier", system_prompt, user)`
- User prompt: both record payloads as JSON
- Returns bool: same entity or not
- If LLM unavailable → pair queued for human (conservative: wrong merge > missed merge)

External API: Ollama `/api/chat` or OCI GenAI Chat at frontier tier.

#### Clustering and golden record

After all pairs are routed (or after the exact-ID fast path groups
records), `UnionFind.groups()` produces clusters of merged record IDs.

For each cluster:
```python
_materialize(member_ids, by_id, pair_scores, ontology_type, policy)
```

Builds the golden record. **This is more than "highest confidence wins":**

- `resolve_run()` loads a **survivorship policy** for the workspace
  (`make_workspace_store().get_survivorship(workspace_id)`), defaulting to
  strategy `"most_complete"` if the workspace hasn't configured one.
  Available strategies are `first_non_empty`, `source_priority`,
  `most_recent`, `most_complete`, and `most_frequent`.
- With `"most_complete"` (the default), each attribute's surviving value is
  the one from the contributing record whose value looks most "complete"
  for that field (ties broken by the lowest record id) — **not** simply the
  member with the single highest overall resolution-confidence score.
- Conflicting values (any losing contribution) are logged to
  `aryx_attribute_conflict`.
- `cluster_confidence(edges, n_members)` still computes an entity-level
  confidence score from the pairwise match scores inside the cluster — this
  score describes *how sure the resolver is these records are the same
  entity*, separately from which value won for each attribute.
- If, for some reason, no policy object is available at all, resolution
  falls back to the simpler `golden_record_weighted()` — highest-confidence
  member's value wins per attribute. In the current `/confirm` code path
  this fallback is not actually reachable (a policy is always constructed),
  but it exists as a defensive default.

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
| `strategy` | the survivorship strategy that decided the winner, e.g. "most_complete" |

**Table: `aryx_adjudication`** (pairs in review band)

| Column | Value |
|--------|-------|
| `left_record_id` / `right_record_id` | the pair |
| `score` | similarity score |
| `llm_verdict` | bool or None if LLM unavailable |
| `status` | "pending" or "auto_llm" |

**Ontology type seeding (idempotent):**
```python
onto.seed_types([OntologyType(name=ontology_type, attributes=list(match_keys),
                              status="approved", source="pipeline")])
```
→ INSERT INTO `aryx_ontology_type` ON CONFLICT DO NOTHING — ensures the type appears in the Browse tab immediately. Runs after every `run_pipeline()` call (progress label `"Seed"`, ~65%), not just once per `/confirm` request.

---

### Stage 3/5 — Relate (LLM Relationship Inference)

**File:** `pipeline/enrich.py:_relate()`
**Triggered when:** `relate=True` for this particular `run_pipeline()` call — always true for the approved-types path; for tabular files, only the last file, and only when `ARYX_INGEST_RELATE=true` (default off — see above).

`_relate()` does **not** simply loop over every possible entity pair — for
workspaces with many entities that would be far too many LLM calls. Instead:

1. Pulls a small type-aware sample of entities per ontology type
   (`store.list_entities_typed_sample(n)`), so every type in the workspace
   is represented in the sample even if one type vastly outnumbers the
   others.
2. Builds a candidate pair list, **cross-type pairs first** (round-robined
   across every pair of types so no single type-combo eats the whole
   budget), then fills any remaining budget with same-type pairs.
3. Caps the candidate list at `effective_pairs = min(ARYX_MAX_RELATE_PAIRS,
   number_of_cross_type_combinations)`. **`ARYX_MAX_RELATE_PAIRS` defaults
   to 10, not 100** — this is a true hard cap; the schema-wide inference
   pass below (3b) is what covers full-population FK discovery, so this
   sampled pass only needs a representative sample, not exhaustive coverage.
4. Adds a "coverage guarantee": if the round-robin above still leaves some
   type completely unrepresented in the candidate list, one extra pair is
   added forcing that type against the most-sampled type, so no type is
   silently skipped.
5. Runs the LLM calls concurrently (`ARYX_RELATE_WORKERS`, default 4) and
   abandons any still-pending calls after `ARYX_RELATE_PAIR_TIMEOUT`
   seconds (default 30s) of no progress — a stuck LLM call must not hang
   the whole ingest; anything abandoned here can still be picked up by the
   relate-isolated safety net (3.5, below) or the FK Link pass.

**External API:** Ollama `/api/chat` or OCI GenAI Chat at frontier tier.

**Table: `aryx_relationship`**

| Column | Value |
|--------|-------|
| `workspace_id` | workspace |
| `source_entity_id` (FK) | from `aryx_entity` |
| `target_entity_id` (FK) | from `aryx_entity` |
| `name` | e.g. "INVOICE_BELONGS_TO_CUSTOMER" |
| `confidence` | float |

#### 3b — Schema-wide FK inference (new — not previously documented)

**File:** `pipeline/enrich.py:_infer_schema_fk_links()`
**Triggered when:** `relate=True` (same gate as Stage 3 above), runs immediately after it.

The sampled pairs in Stage 3 only look at a handful of entities per type —
enough to guess a relationship *exists*, but not guaranteed to spot every FK
column, especially for shared-value joins that don't follow an `_id`/`_name`
naming pattern. This step makes **one (or a few, batched) LLM call(s) across
all entity type *schemas*** — column names only, one sample entity per type,
not the full data — asking the LLM which attributes across types look like
foreign keys. When there are more than 8 types, the schemas are split into
overlapping batches (max 8 types per call, always including the type with
the most FK-looking columns as an "anchor" so cross-batch links involving it
are still found).

Whatever FK specs the LLM proposes are applied the same way Stage 4 applies
them — via `link_by_attribute()` — except this pass creates edges for
**every** matching entity in the workspace, not just the small sample that
was shown to the LLM.

**External API:** same frontier-tier chat call as Stage 3/Stage 3b's parent, via `infer_fk_links()`.

---

### Stage 4/5 — FK Link (cross-file join)

**File:** `pipeline/fk_edges.py:link_by_attribute()`
**Triggered when:** `fk_links` is non-None (last approved file only, or a schema-level spec from 3b above).

For each FK spec from `_detect_fk_links()` / `_detect_fk_links_workspace()` / the schema-inference pass:
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

#### 4b — Relate-Isolated safety net (new — not previously documented)

**File:** `pipeline/enrich.py:_relate_isolated()`
**Triggered:** always, for every `run_pipeline()` call — this is **not** gated by the `relate` flag. It runs right after the FK Link stage, right before Project.

Even after sampled relate (Stage 3) and FK linking (Stage 4), some entities
can still have zero edges — e.g. a tabular file where `relate` was never
enabled and no FK column happened to match. `_relate_isolated()` is the
final backstop:

1. Finds every entity in the workspace with no relationship edge at all
   (`store.list_isolated_entities()` — one query, not one call per entity).
2. Groups the isolated entities **by type**, and picks one anchor entity per
   *other* type already present.
3. Makes **one LLM call per isolated type** (not per isolated entity) asking
   whether that type relates to the anchor type.
4. If yes, creates one edge from **every** isolated entity of that type to
   the anchor entity.

**Why type-level, not entity-level:** for a large XML upload with 20+ entity
types and thousands of rows, this keeps the LLM call count bounded at
roughly "number of isolated types" (at most ~20), never "number of isolated
entities" (which could be in the thousands). This is what guarantees "no
isolated nodes after ingest" as a hard rule, independent of whether `relate`
was turned on for this call.

---

### Stage 5/5 — Project to Graph

**File:** `project.py:project_graph()`
**Triggered when:** `skip_graph` is `False` for this call — always true for the approved-types path; for tabular files, only the last one (see above).

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

When `skip_graph=True` (every non-last tabular file), this stage is skipped
entirely — the summary dict returned still reports whatever `nodes_written`
/ `edges_written` counts were carried over from the previous call, since
those keys only get their real values on the call that actually projects.

---

## External APIs Called

### API A — Embedding (Stage 2/5 — per block)

Same backends as `/read` step 6/8.

**Triggered:** during `_block_embeddings()` inside the resolve funnel — once per block per `run_pipeline` call, and only when the exact-ID fast path (2.0) did not apply.

**Request:** same as `/read` API Call B — batch of match texts.

**Skipped when:** `ARYX_ER_AUTO_MERGE >= 1.0 AND ARYX_ER_ADJUDICATE >= 1.0` (exact-match-only mode), or when `exact_ids` mode (2.0) applied to the whole run.

---

### API B — LLM Adjudication (Stage 2/5 — per pair in [0.90, 0.92) band)

**File:** `resolution/adjudicate.py:adjudicate()`
**Tier:** frontier (highest quality)

```
POST http://ollama:11434/api/chat
{
  "model": "llama3.2:3b",     ← frontier tier (menial/reason model share the same default in this deployment)
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

### API C — Frontier LLM Enrichment (Stage 3, Stage 3b, Stage 4b)

Three different call sites share the same frontier-tier chat mechanism
(`complete_json(broker, "frontier", ...)` in `aryx/relationships.py`):

**C1 — Relationship inference (Stage 3, `_relate()`):** for each sampled
candidate entity pair (capped by `ARYX_MAX_RELATE_PAIRS`, **default 10**):
```
{"role": "user", "content":
  "{\"entity_a\": {attrs}, \"entity_b\": {attrs}}
   Is there a meaningful named relationship between these?"}
→ {"has_relationship": true, "name": "INVOICE_ISSUED_BY", "confidence": 0.87}
```

**C2 — Schema FK inference (Stage 3b, `_infer_schema_fk_links()`):** one
call (or a few batched calls for >8 types) with column names only, across
all type schemas at once, asking which attributes look like FK columns.

**C3 — Isolated-entity inference (Stage 4b, `_relate_isolated()`):** one
call per isolated *type* (not per entity), asking whether that type relates
to a sampled anchor entity of some other already-connected type.

All three are best-effort: a failed or timed-out call for one pair/type is
logged and skipped, it never fails the whole ingest.

---

## Decision Matrix — Which APIs Are Called

| Condition | A · Embed | B · Adjudicate | C · Relate family |
|-----------|-----------|----------------|--------------------|
| Document types (approved_types) | Yes (per block), unless exact-ID mode | Only in [0.90,0.92) | Yes — always relate=True |
| Tabular files — non-last | Yes (per block), unless exact-ID mode | Only in [0.90,0.92) | No — `relate=False` always |
| Tabular files — last file | Yes (per block), unless exact-ID mode | Only in [0.90,0.92) | Only if `ARYX_INGEST_RELATE=true` (default off) |
| All match_keys are `id`/`uuid`/`guid`/`key` | No — exact-ID fast path (2.0) skips embedding | No — exact-ID fast path skips scoring entirely | Unaffected — relate operates on resolved entities, not raw records |
| `er_auto_merge=1.0 AND er_adjudicate=1.0` | No (skip embed) | No | Unaffected |
| Zero mentions for approved type | No (empty connector) | No | No |
| Stage 4b — relate-isolated | — | — | Yes, always runs (not gated by `relate`), one call per isolated type |
| Local mode | Ollama `/api/embed` | Ollama `/api/chat` | Ollama `/api/chat` |
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
| `aryx_ontology_type` | INSERT (idempotent) | After stage 2, every call | seed_types ON CONFLICT DO NOTHING |
| `aryx_relationship` | INSERT | Stage 3 (LLM relate) + Stage 3b (schema FK) + Stage 4 (FK link) + Stage 4b (relate-isolated) | |
| Source catalog (via `DatasourceStore`) | INSERT/UPSERT | Before file loop | `_persist_xml_sources()` — XML/XLSX provenance only |
| FalkorDB / Oracle Graph | MERGE/INSERT | Stage 5 — project_graph | nodes + edges, skipped when `skip_graph=True` |

---

## Error Paths

| Error | Where | Behaviour |
|-------|-------|-----------|
| `discovery_id` not found | HTTP handler | HTTPException 404 |
| `discoveries.get(did)` returns None | `_confirm_job` | ValueError → job marked failed |
| Process restart between /read and /confirm | `_confirm_job` | ValueError "discovery expired" — re-run /read |
| Empty mention list for approved type | `ingest_confirmed` | `run_pipeline` called with empty connector — zero entities, no error |
| `approved_files` entry doesn't match any plan | `ingest_confirmed` | Silently dropped — not an error, not logged as a failure |
| Non-last tabular file's `run_pipeline` call raises | `ingest_confirmed._run_one_plan` (parallel pool) | Exception caught + logged, filename added to a `failed` list; ingestion continues with the remaining files |
| Last tabular file's `run_pipeline` call raises | `ingest_confirmed._run_one_plan` (serial) | Exception propagates → job marked failed |
| `aryx_runs` INSERT fails | Stage 1 | Exception → job failed for this type/file |
| Embed unavailable for a batch | Stage 2 blocking | Silent fallback to string-only scoring for that batch |
| LLM adjudication unavailable | Stage 2 threshold | Pair queued for human (`aryx_adjudication` status=pending) |
| Relate LLM unavailable/timed out for a pair | Stage 3 | That pair is logged + skipped; does not fail the job — abandoned pairs beyond the idle timeout are picked up (if possible) by the Stage 4b safety net |
| Schema FK inference LLM call fails | Stage 3b | Logged and skipped for that batch — best-effort, never fails the job |
| FK link finds no matches | Stage 4 | No writes, continues silently |
| Relate-isolated LLM call fails for a type | Stage 4b | Logged and skipped for that type — best-effort, never fails the job |
| FalkorDB unreachable | Stage 5 | Exception → job failed (only for the call that actually projects, i.e. the last file / each approved type) |
| Oracle Graph unavailable | Stage 5 | Exception → job failed |
| Post-ingest validation check fails | After all types/files complete | Logged only (`logger.warning` per failing check) — never fails the job |
| `OntologyStore` lookup for workspace FK detection fails | Before file loop | Logged, `known_types` treated as empty — Pass B FK detection just finds nothing this run |

---

## How This Connects to /read

```
/read  →  aryx_document    (step 4/8)
       →  aryx_chunk        (step 5/8)
       →  aryx_chunk_embedding  (step 7/8)
       →  discoveries._STORE[did]  (mentions + tabular plans, in process memory)

/confirm  →  aryx_runs          (stage 1 — one per approved type/file)
          →  aryx_landed        (stage 1 — one per mention/row)
          →  aryx_entity        (stage 2 — canonical entities)  ← ENTITIES CREATED HERE
          →  aryx_entity_member (stage 2 — provenance)
          →  aryx_adjudication  (stage 2 — human queue items)
          →  aryx_relationship  (stages 3, 3b, 4, 4b — graph edges)
          →  FalkorDB / Oracle Graph  (stage 5 — last file / each type only)
```

The `/read` infrastructure writes (aryx_document, aryx_chunk, aryx_chunk_embedding)
persist regardless of whether `/confirm` is ever called. They power `/ask` RAG
retrieval independently of the entity resolution path.

---

## Related Files

| File | Role |
|------|------|
| `src/aryx/api/doc_discover_api.py` | HTTP handlers — `/read`, `/summary`, `/confirm` |
| `src/aryx/pipeline/doc_discovery.py` | `ingest_confirmed()`, `_detect_fk_links()`, `_detect_fk_links_workspace()`, `_xml_to_csvs()`, `_xlsx_to_csvs()`, `_persist_xml_sources()` |
| `src/aryx/pipeline/orchestrate.py` | `run_pipeline()` — stages 1–5 (incl. 3b schema-FK, 4b relate-isolated) |
| `src/aryx/discover.py` | Stage 1 — `discover()` → `run_spine()` → land records |
| `src/aryx/pipeline/run.py` | `run_spine()` — extract + clean + profile + batch-land |
| `src/aryx/resolve_entities.py` | Stage 2 entry — `resolve_run()` — loads survivorship policy, decides exact-ID mode |
| `src/aryx/resolution/run.py` | Resolution funnel — `resolve()`, `_resolve_exact()`, block + score + route + cluster |
| `src/aryx/resolution/classical.py` | `block()`, `score_pair()` |
| `src/aryx/resolution/adjudicate.py` | LLM adjudication — `adjudicate()` |
| `src/aryx/resolution/cluster.py` | `UnionFind`, `golden_record_weighted()` (fallback path) |
| `src/aryx/resolution/golden.py` | `golden_record_with_policy()` (primary path) |
| `src/aryx/resolution/survivorship.py` | `SurvivorshipPolicy`, strategy resolution (`most_complete`, etc.) |
| `src/aryx/resolution/confidence.py` | `cluster_confidence()`, `cluster_edges()` |
| `src/aryx/resolution/review_queue.py` | `StoreReviewSink` — writes the human-review queue |
| `src/aryx/store/adjudication_store.py` | `AdjudicationStore` — backs the review queue |
| `src/aryx/pipeline/enrich.py` | Stage 3 — `_relate()`; Stage 3b — `_infer_schema_fk_links()`; Stage 4b — `_relate_isolated()`; `_build_type_ancestors()` |
| `src/aryx/relationships.py` | `infer_relationship()`, `infer_fk_links()` — the actual frontier LLM calls used by enrich.py |
| `src/aryx/pipeline/fk_edges.py` | Stage 4 — `link_by_attribute()` |
| `src/aryx/pipeline/ingest_validation.py` | Post-ingest zero-loss validation — `ground_truth_from_tabular()`, `validate_workspace()` |
| `src/aryx/pipeline/stages.py` | `StageRunner` — per-run stage checkpoint/resume guard |
| `src/aryx/store/checkpoint_store.py` | `StageTracker` — durable per-stage status rows |
| `src/aryx/project.py` | Stage 5 — `project_graph()` |
| `src/aryx/store/entity_store.py` | `save()`, `landed_records()`, `save_relationships()`, `list_entities_typed_sample()`, `list_isolated_entities()` |
| `src/aryx/store/postgres_store.py` | `start_run()`, `finish_run()`, `save_profiles()` |
| `src/aryx/store/batch_sink.py` | Batched `aryx_landed` INSERT |
| `src/aryx/store/ontology_store.py` | `seed_types()` — idempotent type registration |
| `src/aryx/store/datasource_store.py` | `DatasourceStore` — backs `_persist_xml_sources()` and `restore_generic_source_entry()` |
| `src/aryx/source_catalog.py` | `upsert_xml_catalog_entry()`, `xml_asset_record()`, `restore_generic_source_entry()` |
| `src/aryx/discoveries.py` | In-process discovery result store (put/get/expire) |
| `src/aryx/graph/oracle_graph_store.py` | Oracle Graph writer (OCI mode) |
| `src/aryx/graph/__init__.py` | FalkorDB writer (local mode) |

---

## Documentation Corrections Log

This file was audited against the current source on 2026-07-16 and found to
have drifted in several places. Changes made, and why:

1. **Multi-sheet Excel (`.xlsx`) support was completely missing.**
   `doc_discovery.py:_xlsx_to_csvs()` expands one workbook into one derived
   CSV plan per visible worksheet before `/confirm` ever runs, exactly like
   the existing XML expansion. Added a new "Where the files actually come
   from" section explaining this, and the naming convention
   (`{stem}__{sheet_slug}.csv`) `approved_files` must use.
2. **A second FK-detection pass, `_detect_fk_links_workspace()`, was not
   documented at all.** It matches the last approved file's columns against
   ontology types already registered from *previous* confirms in the same
   workspace — this is what makes single-file confirm jobs still pick up FK
   links, which the in-batch `_detect_fk_links()` alone cannot do. Added as
   "Pass B" under FK detection.
3. **`_persist_xml_sources()` (source-catalog provenance for XML/XLSX
   uploads) was entirely undocumented.** Added as its own step.
4. **`relate=True` was claimed to be unconditional for the tabular-files
   pipeline call.** The actual code is `relate=is_last and
   settings.ingest_relate`, and `ARYX_INGEST_RELATE` **defaults to
   `False`.** Rewrote the tabular-path pipeline-call section and the
   decision matrix to reflect this, with the "why" (large CPQ payloads can
   hang the LLM call).
5. **`skip_graph` was not mentioned anywhere**, even though it fundamentally
   changes when the graph gets written: every non-last tabular file skips
   graph projection; only the last file (or each approved type — see #7)
   projects. Documented, with the FalkorDB `clear()`-then-rebuild race
   condition that makes this necessary.
6. **Parallel execution of non-last tabular files (`ThreadPoolExecutor`,
   `ARYX_INGEST_WORKERS`, default 3) and the partial-failure-tolerant
   behaviour (non-last file failures are logged and skipped, not fatal)
   were not documented.** Added, including error-path table rows.
7. **The approved-types loop's `run_pipeline` call passes no `skip_graph`
   and no gating on `relate`,** so — unlike the tabular path — every
   approved type gets `relate=True` *and* an immediate full graph rebuild.
   The old doc implied one shared pipeline pass; added an explicit "why
   this matters" callout since this means N types → N sequential graph
   rebuilds.
8. **Two new pipeline sub-stages in `orchestrate.py:run_pipeline()` were
   entirely missing:** the schema-wide LLM FK-inference pass
   (`_infer_schema_fk_links()`, gated by `relate=True`, folded in as "Stage
   3b") and the relate-isolated safety net (`_relate_isolated()`, runs
   **unconditionally** regardless of the `relate` flag, folded in as "Stage
   4b"). Both added with full mechanics and their own API callouts.
9. **`ARYX_MAX_RELATE_PAIRS` was documented with a default of 100; the
   actual default in `config.py` is 10.** Corrected everywhere it's
   mentioned, and expanded the Stage 3 description to explain the
   type-aware sampling and coverage-guarantee logic that decides which
   pairs get evaluated (previous version implied a flat "for each pair"
   loop).
10. **The exact-ID fast path (`ARYX_ER_EXACT_ID_MATCH`, default `True`) in
    entity resolution was undocumented.** When all match keys are
    `id`/`uuid`/`guid`/`key`, resolution skips blocking/embedding/scoring
    entirely and merges on exact string equality instead — added as new
    step "2.0" with the rationale (fuzzy scoring is unsafe for sequential
    numeric ids).
11. **The golden-record merge description ("highest-confidence member
    wins") described only the fallback path.** The primary path uses a
    per-workspace `SurvivorshipPolicy` (default strategy `"most_complete"`)
    via `golden_record_with_policy()`; `golden_record_weighted()` is a
    defensive fallback not normally reached from `/confirm`. Corrected and
    explained both paths.
12. **Post-ingest zero-loss validation (`pipeline/ingest_validation.py`)
    was not mentioned at all**, despite running after every `/confirm`
    job with tabular files. Added as its own step, with an explicit note
    that it is log-only and best-effort (never fails the job).
13. **Resume/checkpoint support (`resume_run_id`, `StageRunner`,
    `StageTracker`) was undocumented.** `/confirm` doesn't currently use it,
    but it's part of `run_pipeline()`'s real signature and explains
    checkpoint rows engineers may see in the database — added a short
    resilience note under Stage 1.
14. Minor: `RecordsConnector(recs)` in the approved-types path is actually
    called as `RecordsConnector(recs, label=otype)` — corrected the code
    snippet.
15. Expanded the "Related Files" table with modules that were referenced
    implicitly but never listed: `survivorship.py`, `confidence.py`,
    `review_queue.py`, `adjudication_store.py`, `relationships.py`,
    `ingest_validation.py`, `stages.py`, `checkpoint_store.py`,
    `datasource_store.py`, `source_catalog.py`.

---

*Previous: `doc-discover-read.md` — the `/read` flow that populates the discovery store.*
