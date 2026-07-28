# aryx Scalability Bottlenecks — Analysis & OCI Fix Path

This document covers every identified bottleneck in aryx at scale, with exact
source locations, accuracy impact, resource impact, cost impact, and the OCI fix path.

**Scale threshold:** aryx works well up to ~100K entities on a 16 GB VM.
Beyond that, the bottlenecks below cause degraded accuracy, OOM crashes, or
unacceptably slow pipeline runs.

---

## Bottleneck Index

| # | Severity | Component | Trigger point |
|---|---|---|---|
| P1 | ✅ Fixed | Graph projection — `fetchall()` (confirmed already fixed in code) | >500K entities |
| P2 | 🔴 Critical | Rule evaluator — Python loop | >100K entities × rules |
| P3 | 🟡 High | Resolution blocking — silent drop | Blocks >5,000 records |
| P4 | 🟡 High | Single-threaded pipeline worker | Large file batches |
| P5 | 🟢 Medium | FalkorDB query hard cap | >500 entity results |
| P6 | 🟢 Medium | Relationship inference cap | >50 entity pairs |
| P7 | 🟢 Medium | Transitive closure cap | Hierarchies >4 hops deep |
| P8 | 🔴 Critical | Schema-FK link stage — per-spec entity refetch | *(fixed)* >~10 candidate FK specs (OCI mode) |
| P9 | 🟡 High | Resolution adjudication — serial per-pair LLM calls | *(fixed)* pairs in adjudicate band |
| P10 | 🟡 High | Chunk/embedding store — per-row round-trips | *(fixed)* any multi-chunk document (OCI mode) |
| P11 | 🟡 High | Chunk embedding — unbatched OCI GenAI calls | *(fixed)* documents producing >~50 chunks (OCI mode) |
| P12 | 🔴 Critical | Graph projection — 25-row batch cap on Oracle writes | *(fixed)* >~1,000 entities/relationships (OCI mode) |
| P13 | 🔴 Critical | CPQ product config load — per-attribute `neighbors()` N+1 | *(fixed)* >~50 config attrs on a product (OCI mode) |
| P14 | 🔴 Critical | Datasource/action/relationship-type writes — missing `workspace_id` scoping | *(fixed)* cross-tenant delete/write, any workspace |
| P15 | 🔴 Critical | Discovery summary/confirm — full 257MB payload deserialized for a small read | *(fixed)* any multi-file discovery (OCI mode) |
| P16 | 🟡 High | Oracle `RETURNING...INTO` ~16KB limit on JSON columns | *(fixed)* any datasource config json >~16KB (OCI mode) |
| P17 | 🟢 Medium | Schema-FK LLM inference — sequential batches, not parallelized | *(identified, not fixed)* workspaces with many entity types |
| P18 | 🔴 Critical | Adjudication decide — missing `workspace_id` scoping | *(fixed)* cross-tenant entity-merge approval, any workspace |

---

## P1 — Graph Projection `fetchall()` Memory Spike *(Already Fixed in Code)*

**Status:** ✅ Confirmed fixed during the 2026-07-27 bottleneck sweep — this
section originally proposed the fix below; the codebase already has it. Kept
here as the historical record and because the `fetchall()` anti-pattern it
describes still shows up in one smaller spot (see note at the end).

**Source files (current state):**
- `src/aryx/store/entity_store.py:216-228` — `list_entities()` → named cursor
  (`list_entities_cur_{ws}_{uuid}`) + `fetchmany(batch_size)`, yields as a generator
- `src/aryx/store/entity_store.py:230-240` — `list_members_provenance()` → same pattern
- `src/aryx/store/entity_store.py:253-263` — `list_relationships()` → same pattern
- `src/aryx/project.py` — calls all three; callers that need list semantics
  materialize explicitly (`list(store.list_entities())`), streaming is the default

**What happens now:**
```python
def list_entities(self) -> Iterator[tuple[int, str, dict]]:
    batch_size = get_settings().batch_size   # ARYX_BATCH_SIZE, default 500
    with self._pool.connection() as conn:
        with conn.cursor(f"list_entities_cur_{self._ws}_{uuid.uuid4().hex[:8]}") as cur:
            cur.execute(load("select_entities"), (self._ws,))
            while batch := cur.fetchmany(batch_size):
                yield from ((r[0], r[1], r[2]) for r in batch)
```
All three are generators — only one `batch_size`-sized page is held in Python
memory at a time, exactly the fix originally proposed below.

### Accuracy Impact
**None.** Same rows, same order — this was always true of the fix.

### Resource Impact (historical — the problem this fix solved)
| Dataset size | RAM spike (Python), before fix | After fix |
|---|---|---|
| 100K entities | ~50 MB | ~5 MB constant |
| 500K entities | ~250 MB | ~5 MB constant |
| 1M entities | ~500 MB | ~5 MB constant |
| 5M entities | ~2.5 GB (OOM crash) | ~5 MB constant |

### Remaining note (not urgent)
`src/aryx/graph/oracle_graph_store.py:235` — `add_provenance_batch()`'s
source-id lookup still does a plain `cur.fetchall()` over
`select_graph_sources_by_workspace`. Same anti-pattern, different file, much
smaller blast radius (one row per unique source record, not per entity) —
noted during the 2026-07-27 sweep, not fixed.

### Fix — OCI Path
Oracle ADB via `oracle_pool.py`'s `OracleCursorWrapper` already supports the
identical named-cursor / `fetchmany()` pattern — no adapter changes needed,
this was true for both backends from the start.

---

## P2 — Rule Evaluator Python Loop

**Source files:**
- `src/aryx/reasoning/engine.py:107` — `list_entities()` fetchall
- `src/aryx/reasoning/engine.py:115-124` — nested Python loop over rules × entities

**What happens:**
```python
ents = estore.list_entities()    # fetchall — all entities in RAM
for rule in rules:
    for ent in ents:             # O(rules × entities) Python iterations
        if _match(ent, when):
            fires += _fire(graph, ent, then)
```
At 1M entities with 10 rules = 10 million Python dictionary lookups and
type-checks with no database index involvement.

### Accuracy Impact
**Marginally improves with fix.** Current Python `_match()` silently swallows
`TypeError` and `ValueError` on malformed attribute values:
```python
try:
    return op(val, when.get("value"))
except (TypeError, ValueError):
    return False   # silent miss — valid entity skipped
```
SQL pushdown uses strict type casting — consistent behavior across all rows,
no silent skips.

### Resource Impact
| Dataset | Rules | Python iterations | Time (est.) |
|---|---|---|---|
| 10K entities | 5 | 50K | <1 sec |
| 100K entities | 10 | 1M | ~10 sec |
| 1M entities | 10 | 10M | ~2 min |
| 10M entities | 10 | 100M | ~20 min |

Also suffers from the P1 RAM spike — all entities loaded before loop starts.

### Cost Impact
- Evaluator blocks the API worker thread for its entire duration
- At 1M entities: 2 min blocked worker = API unresponsive during run
- Concurrent users experience timeouts during rule evaluation runs

### Fix — Today (no OCI required)
Push the `when` clause into SQL — database uses indexes, Python only receives matches:

```sql
-- evaluate_rule.sql
SELECT id, ontology_type, attributes
FROM   aryx_entity
WHERE  workspace_id = %(ws)s
  AND  ontology_type = %(type)s
  AND  (attributes->>%(attr)s)::numeric > %(value)s
```

Result: 10 SQL indexed queries instead of 10M Python iterations.
RAM: only matching entities in memory, not the full dataset.

### Fix — OCI Path
Oracle Graph Server (PGX) via `ReasonerPort` adapter eliminates Python
entirely from rule evaluation. PGX applies RDFS++ / OWL 2 RL rules inside
the graph engine — Python calls `evaluate_workspace()` and receives a count.
No Python iterations, no RAM allocation, parallel graph processing internally.

---

## P3 — Resolution Blocking Silent Drop

**Source files:**
- `src/aryx/resolution/blocking.py:78` — `max_block_size = 5000`
- `src/aryx/resolution/blocking.py:100-105` — silent WARNING + skip

**What happens:**
```python
if len(members) > self.max_block_size:  # 5000
    logger.warning("Block '%s' has %d members -- skipping.", key, len(members))
    continue   # entire block dropped — records never resolved
```
Any block with >5,000 records sharing the same prefix/token/Soundex key is
silently skipped. Those records land in Postgres but are never resolved into
entities.

### Accuracy Impact
**Direct data loss.** Entities that should exist in the graph are missing.
Common triggers:
- Datasets with very common names (e.g. "John Smith" in a contacts list)
- Datasets with low cardinality match keys (e.g. "status" field)
- Any dataset where >5,000 records share a common Soundex key

This is the highest accuracy risk at scale — there is no error, no failed
job, no user notification. Records are permanently skipped with a log line.

### Resource Impact
Low — the skip itself is cheap. The impact is missing data, not resource exhaustion.

### Cost Impact
- Invisible — pipeline reports success, job status = completed
- Discovery only happens when users query for data that should exist
- Correction requires re-ingestion with adjusted match keys

### Fix — Today (no OCI required)
Three options:
1. **Raise the cap** (`max_block_size=50000`) — trades safety for coverage
2. **Sub-block large blocks** — split by secondary key before comparison
3. **Alert instead of skip** — surface to human review queue instead of dropping

The cap is now configurable via `ARYX_MAX_BLOCK_SIZE` (default 5000).
The silent-drop behaviour itself is not yet changed — see recommended fix below.

### Recommended Fix — B1: Sub-block + Alert Residual

**Why cross-sub-block misses are narrower than they appear:**

`MultiKeyBlocker` emits three independent key families per record:
```
prefix:john       ← first 4 chars of normalised name
tokens:doe|john   ← sorted unique tokens
soundex:J530      ← phonetic code of first token
```
Each record appears in **all three blocks simultaneously**. A cross-sub-block
miss under the prefix key is caught by the token-set or Soundex block in most
cases. A true miss only occurs when all three key families produce an oversized
block for the same pair — which happens only in extremely low-cardinality
datasets (e.g. 90%+ of records are identical strings).

**B1 algorithm:**

```
Block "prefix:john" → 6,000 members (over cap)
  ↓ _sub_block() splits by secondary token key
  Sub-block "john|smith"   → 180 records  → compared normally
  Sub-block "john|doe"     → 150 records  → compared normally
  Sub-block "john|johnson" → 80 records   → compared normally
  Sub-block "john|"        → 5,200 records → still over cap
    ↓ write to aryx_ingest_question (HITL queue)
    User sees: "Block john| has 5,200 members — action required"
```

**Files to implement:**
- `src/aryx/resolution/blocking.py` — add `_sub_block(members, cap)` method;
  replace `continue` with sub-block attempt, then HITL write for residual
- `src/aryx/store/ingest_question_store.py` — add `create_block_alert(key, count)`
  that writes a `kind="block_overflow"` row to `aryx_ingest_question`

**Outcome:** Most oversized blocks auto-resolve without human intervention.
Genuinely degenerate blocks (still oversized after sub-blocking) surface in
the review panel — no data is silently lost.

### Fix — OCI Path
Oracle Autonomous Database with `oml4py` or OCI Data Flow (Spark via
`ComputePort`) handles arbitrarily large blocks via distributed comparison —
no cap needed.

---

## P4 — Single-Threaded Pipeline Worker

**Source files:**
- `src/aryx/api/file_ingest_api.py:132` — `background_tasks.add_task()`
- `docker-compose.yml` — single `worker` container, no replicas

**What happens:**
FastAPI `BackgroundTasks` runs ingestion in a single thread within the API
process. One file at a time, one pipeline at a time. No parallelism across
files or pipeline stages.

### Accuracy Impact
**None.** Sequential processing produces identical results to parallel.

### Resource Impact
- 10 files uploaded simultaneously → processed one-by-one sequentially
- Each file waits for the previous to complete Discover → Resolve → Project
- Upload of 100 PDFs: if each takes 5 min → 500 min total (8+ hours)
- With parallel workers: same 100 PDFs → ~50 min (10 parallel workers)

### Cost Impact
- Single VM: no additional cost but throughput ceiling is hard
- User-facing: long wait times, perceived system slowness
- OCI Data Flow (Spark): ~$0.02/OCPU/hr — cost scales with parallelism used

### Fix — Today (no OCI required)
Replace `BackgroundTasks` with a proper job queue:
- **Celery + Redis** — adds broker dependency but proven
- **Python multiprocessing** — simpler, no new infra
- **ThreadPoolExecutor** — lightweight, already in `doc_router.py`

### Fix — OCI Path
OCI Data Flow (managed Spark) via `ComputePort` adapter — submit pipeline
jobs as Spark applications, scale workers automatically, pay per use.

---

## P5 — FalkorDB Query Hard Cap at 500

**Source file:**
- `src/aryx/graph/reader.py:63` — `capped = max(1, min(int(limit), 500))`

**What happens:**
```python
capped = max(1, min(int(limit), 500))
"MATCH (e:Entity) {where} RETURN e.id, e.type, e.name LIMIT {capped}"
```
`find_entities()` — used by the Ask flow to look up entities — hard caps
at 500 results regardless of how many matching entities exist in the graph.

### Accuracy Impact
**Direct accuracy loss for Ask queries.** If a question about "all customers
in the US" has 2,000 matching entities, Ask only sees the first 500. Answers
are based on a partial view of the data.

The LLM answer is only as good as the context it receives. At large datasets,
Ask systematically under-counts and misses entities beyond position 500.

### Resource Impact
Low — the cap protects FalkorDB from large result sets. Removing it without
pagination risks memory pressure on FalkorDB.

### Cost Impact
- No direct cost — but incorrect answers from Ask reduce product value
- Enterprise use case impact: compliance queries, counts, aggregations all
  silently return incomplete results

### Fix — Today (no OCI required)
Add pagination to the Ask retrieval flow:
```python
def iter_entities_by_type(self, ontology_type, page_size=500):
    offset = 0
    while True:
        batch = self.find_entities(ontology_type, limit=page_size, offset=offset)
        if not batch:
            break
        yield from batch
        offset += page_size
```

### Fix — OCI Path
Oracle Spatial & Graph (GraphStorePort adapter) — no arbitrary result cap,
PGQL queries return full result sets with native pagination support.

---

## P6 — Relationship Inference Cap at 50 Pairs

**Source file:**
- `src/aryx/pipeline/orchestrate.py:50` — `max_pairs: int = 50`
- `src/aryx/pipeline/enrich.py:43` — `if pairs >= max_pairs: break`

**What happens:**
When `relate=True` is enabled, the pipeline infers relationships between
entities using the LLM. It stops after 50 candidate pairs regardless of
how many entities exist.

### Accuracy Impact
**Significant accuracy loss for relationship coverage.** With 1,000 entities,
there are potentially 499,500 pairs. Only 50 are evaluated — 0.01% coverage.
The knowledge graph is relationship-sparse at scale.

### Resource Impact
The cap exists specifically to control LLM cost — each pair evaluation is
one LLM frontier call. Removing the cap without cost control would be
prohibitively expensive.

### Cost Impact
| Pairs | LLM calls | Estimated cost (frontier tier) |
|---|---|---|
| 50 (current cap) | 50 | ~$0.05 |
| 1,000 | 1,000 | ~$1.00 |
| 10,000 | 10,000 | ~$10.00 |
| All pairs (1K entities) | 499,500 | ~$500 |

The cap is intentional — uncapped LLM relationship inference is not viable.

### Fix — Today (no OCI required)
Replace random all-pairs with **FK-link inference** (`link_by_attribute`) —
deterministic, no LLM, scales to any size. Use LLM only for semantically
ambiguous pairs.

### Fix — OCI Path
OCI Generative AI (LlmPort adapter) — lower cost per call than OpenAI/Anthropic
frontier models. Allows raising the cap cost-effectively.
Oracle Graph Server (PGX) — infers relationships from OWL property axioms
automatically — no LLM calls needed for structurally derivable relationships.

---

## P7 — Transitive Closure Cap at 4 Hops

**Source file:**
- `src/aryx/reasoning/edge_axioms.py:17` — `_TRANSITIVE_MAX = 4`
- `src/aryx/reasoning/edge_axioms.py:42` — hard cap enforced

**What happens:**
```python
_TRANSITIVE_MAX = 4
d = max(2, min(int(depth), _TRANSITIVE_MAX))
for hop in range(2, d + 1):
    graph.run(f"MATCH (a)-[:REL*{hop}..{hop}]->(b)...")
```
Transitive closure (A→B→C→D = A→D) only runs up to 4 hops deep.

### Accuracy Impact
**Missing inferences for deep hierarchies.** Common real-world cases that
exceed 4 hops:
- **Org charts:** CEO → VP → Director → Manager → Team Lead → Employee (5 levels)
- **Geography:** Continent → Country → State → City → District → Suburb (6 levels)
- **Product taxonomy:** Category → Subcategory → Type → Variant → SKU (5 levels)
- **Legal entities:** Parent → Holding → Subsidiary → JV → SPV (5 levels)

All of these produce incorrect "is part of" / "reports to" / "located in"
relationship answers beyond 4 levels.

### Resource Impact
Each hop requires one FalkorDB Cypher query. Cap prevents runaway on cyclic
graphs — without it, a cycle would loop forever.

### Cost Impact
Low direct cost — graph queries are cheap. Impact is accuracy loss, not
resource cost.

### Fix — Today (no OCI required)
Increase `_TRANSITIVE_MAX` to 8 or 10 and add cycle detection:
```python
_TRANSITIVE_MAX = 8
# Add: WHERE NOT (a)-[:REL*1..{hop-1}]->(b)  to skip already-inferred edges
```

### Fix — OCI Path
Oracle Graph Server (PGX) with `owl:TransitiveProperty` — unbounded closure
with internal cycle detection. No hop cap, no manual Cypher, correct for
any hierarchy depth.

---

## P8 — Schema-FK Link Stage: Redundant Per-Spec Entity Refetch *(Fixed)*

**Status:** ✅ Fixed 2026-07-27. Identified live on a real OCI-mode ingest, fix
implemented, verified via new unit tests (`tests/test_fk_edges.py`, 4/4 passed),
deployed to the running `api` container.

**Source files:**
- `src/aryx/pipeline/fk_edges.py:43` — `link_by_attribute()` calls `list(estore.list_entities())`
- `src/aryx/pipeline/orchestrate.py:130-137` — schema-FK loop (`_infer_schema_fk_links` results), one call per spec
- `src/aryx/pipeline/orchestrate.py:148-158` — deterministic `fk_links` loop, same pattern

**What happens:**
```python
def link_by_attribute(estore, source_type, source_attr, target_type, target_attr, name):
    entities = list(estore.list_entities())   # full workspace refetch, EVERY call
    ...
```
`_infer_schema_fk_links()` proposes one FK spec per plausible cross-type attribute
match (batched 8 entity-types per LLM call). Each spec is applied via
`link_by_attribute()`, which re-fetches and JSON/CLOB-decodes **every entity in
the workspace from scratch**, on every single spec — an O(N_specs × N_entities)
refetch where a single O(N_entities) fetch would do.

### Accuracy Impact
**None.** Same relationships are produced either way — this is pure wasted work,
not a correctness issue.

### Resource Impact — measured live, not estimated
Observed on a 30-file CPQ ingest (workspace 321, job `dab8873c...`, 2026-07-27):

| Metric | Value |
|---|---|
| Entity types in workspace | 30 |
| `link_by_attribute` calls observed | 31 (job still running) |
| Per-call duration | min 31.4s / avg 45.9s / max 62.2s |
| Correlation with match count | **None** — a call saving 8,354 relationships took ~38s; calls saving 0 took 31-62s |
| Link stage duration so far | 26m29s (still running) |
| Estimated total specs (30 types, batched 8/call) | ~35-50 |
| Estimated total Link-stage duration | 25-40 minutes |

The lack of correlation between duration and match count confirms the refetch
(network round-trip + JSON/CLOB decode of the full entity table), not the
in-memory join, is the dominant cost.

### Cost Impact
- Each refetch is a real network round-trip to Oracle ADB 23ai (`us-chicago-1`)
  plus per-row LOB/JSON decode — no dollar cost (no LLM call), but this is the
  single largest time cost in the pipeline once resolution/relate are fixed (P9).
- On a 30-type workspace this stage alone was projected to take 25-40 minutes —
  longer than the rest of the pipeline (Discover+Resolve+Seed+Project for all
  30 files together took 7m18s; Relate took 4m54s).

### Fix Applied
`link_by_attribute()` now takes an `entities` parameter instead of calling
`estore.list_entities()` internally. Fetch happens once, result is reused
across every spec:
```python
entities = list(estore.list_entities())   # once
for spec in schema_links:
    link_by_attribute(estore, entities, spec["source_type"], ...)   # no refetch
```
Fixed at **all four call sites** that loop over FK specs, not just the
pipeline orchestrator — the same N+1 pattern existed in two API endpoints too:
- `src/aryx/pipeline/orchestrate.py` — `schema_fk` and `fk_link` loops (share
  one fetch across both, since neither creates new entities)
- `src/aryx/api/data_api.py` — `/relate` endpoint
- `src/aryx/api/workspace_api.py` — `/auto-link` endpoint

Verified via `tests/test_fk_edges.py` (4/4 passed), including a regression
guard that fails if `link_by_attribute()` ever calls `list_entities()` again.

**Projected improvement** (from the measured data that identified this): 1 fetch
(~46s) instead of N, each subsequent spec becomes a low-cost in-memory dict lookup.

| Specs (N) | Before (N × ~46s) | After (~46s + N × ~2s) | Reduction |
|---|---|---|---|
| 31 (observed) | ~23.8 min | ~2.3 min | ~90% |
| 40 (est.) | ~30.7 min | ~2.8 min | ~91% |
| 50 (est.) | ~38.3 min | ~3.3 min | ~91% |

Secondary gap noted in the same investigation, not yet fixed: no
`update_stage()` call happens between the start and end of the Link stage
(same missing-progress pattern P9 had for Resolve before its fix) — the job
status/UI shows the stage frozen at one static message for the entire
duration, even though real work is happening underneath.

### Fix — OCI Path
This is a Python-side architecture issue, not a backend limitation — the fix
applies identically regardless of DB backend. Oracle Graph Server (PGX) could
in principle compute these joins server-side via property-graph matching,
eliminating the Python double-loop entirely, but the immediate 90%+ win comes
from removing the redundant fetch, not from a backend change.

---

## P9 — Resolution Adjudication: Serial Per-Pair LLM Calls *(Fixed)*

**Status:** ✅ Fixed 2026-07-27 via `.env` threshold consolidation.

**Source files:**
- `src/aryx/resolution/run.py` — `_route_pair()` → `adjudicate()`, called inside
  the nested block/pair loop in `resolve()`
- `src/aryx/resolution/adjudicate.py:52` — one `complete_json(broker, "frontier", ...)`
  HTTP call to OCI GenAI per pair scoring in `[ARYX_ER_ADJUDICATE, ARYX_ER_AUTO_MERGE)`

**What happened:**
Every candidate pair whose similarity score landed in the adjudicate band
(default `[0.90, 0.92)`) triggered a synchronous, unbatched network call to
OCI GenAI Command R+ — one HTTP round-trip per pair, fully serial, inside a
loop capped at `ARYX_MAX_PAIRS_PER_BLOCK` (2000) pairs per block across
potentially thousands of blocks. Live logs showed multi-minute gaps between
block completions on a 8,354-record resolve run, entirely explained by this
per-pair LLM latency.

### Fix Applied
`ARYX_ER_AUTO_MERGE=0.95` and `ARYX_ER_ADJUDICATE=0.95` in `.env` — setting
the two thresholds equal collapses the adjudicate band to zero width. Pairs
scoring ≥0.95 auto-merge with no LLM call; everything else falls straight to
the review/reject path. This eliminates the per-pair OCI GenAI calls entirely
for this workspace's matching profile.

**Secondary fix (same investigation):** `resolve()` in `run.py` previously
reported progress to `job_events` only once at the start of the entire resolve
stage (`_emit("Resolve", 38, "N records loaded...")`), then not again until
the stage fully completed — even though it internally processes thousands of
blocks over many minutes. Added `on_block_progress` callback, fired every 25
blocks, threaded through `resolve_entities.py`'s `resolve_run()` into
`jobs.update_stage()`, so the UI now shows real incremental movement instead
of looking frozen. Verified via `tests/test_resolution_funnel.py` (8/8 passed).

### Cost Impact
- Before: N pairs in the adjudicate band × 1 LLM call each, fully serial
- After: 0 LLM calls for this workspace's threshold profile — pure string/embedding
  scoring decides every pair
- Trade-off: pairs that would have gone to LLM adjudication (nuanced,
  borderline-similarity matches) now either auto-merge (≥0.95) or fall to the
  review queue / auto-reject — a precision/recall trade for speed, not free

---

## P10 — Chunk/Embedding Store: Per-Row Round-Trips *(Fixed)*

**Status:** ✅ Fixed 2026-07-27, verified via new unit tests, deployed to running `api` container.

**Source files:**
- `src/aryx/store/chunk_store.py` — `save_chunks()`, `save_embeddings()`
- `src/aryx/queries/insert_chunk.sql`, `src/aryx/queries/select_chunk_ids_by_doc.sql`
  (+ `src/aryx/queries/oracle/select_chunk_ids_by_doc.sql`)

**What happened:**
```python
for chunk in chunks:
    cur.execute(load("insert_chunk"), (...))   # one round-trip PER CHUNK
    row = cur.fetchone()
```
Both methods looped with an individual `cur.execute()` per row — for a
document split into ~200 chunks, ~200 sequential round-trips to Oracle ADB in
`us-chicago-1` for chunk text, plus ~200 more for embeddings. Every round-trip
is a real internet hop (TCPS, port 1522), not a local call. `entity_store.py`
already solved this exact problem for entity saves (`executemany_returning`,
3 round-trips regardless of batch size) — `chunk_store.py` had never been
upgraded to match.

### Fix Applied
`save_chunks()`: one `executemany()` insert (with `ON CONFLICT DO NOTHING`
preserved for re-ingest idempotency) + one bulk `SELECT ... WHERE chunk_index
= ANY(%s)` (Oracle: `JSON_TABLE` override, same pattern as
`select_landed_by_ids`) to recover generated ids in the original chunk order —
**2 round-trips total regardless of document size**, down from ~N.
`save_embeddings()`: one `executemany()` call — **1 round-trip**, down from N.

Verified via new `tests/test_chunk_store.py` (7/7 passed): single-executemany
assertion, id-mapping-by-chunk_index (not fetch order) assertion, empty-input
no-op assertion.

### Cost Impact
- Before: ~400 round-trips per ~200-chunk document (chunks + embeddings)
- After: ~3 round-trips per document
- Applies to every document ingested in OCI mode — compounding benefit across
  the whole document-parsing pipeline, independent of the P8/P9 fixes above

---

## P11 — Chunk Embedding: Unbatched OCI GenAI Calls *(Fixed)*

**Status:** ✅ Fixed 2026-07-27, verified via new unit tests, deployed to running `api` container.

**Source files:**
- `src/aryx/broker/__init__.py:150-158` — `_oci_embed()` sends `inputs=texts`
  to `EmbedTextDetails` in one call, whatever size `texts` is
- `src/aryx/pipeline/embed.py:41-42` — `embed_chunks()` called `broker.embed(texts)`
  with the *entire* document's chunk list in one request

**What happened:**
```python
texts = [c.text for c in chunks]     # could be 100+ for a modest document
vectors = broker.embed(texts)        # one OCI GenAI / Cohere Embed call, no cap
```
`ARYX_CHUNK_SIZE` defaults to 1000 characters, so any document over roughly
100K characters (a modest 50-100 page PDF) produces 100+ chunks sent in a
single embed request. Cohere Embed v3 (native or via OCI GenAI) has a
per-request input cap well under that. The resolution path already knew to
sub-batch (`resolution/run.py:44`, `embed_batch_size` default 50) —
`embed_chunks()` had never been given the same treatment.

### Accuracy Impact
**None if it succeeds.** The real risk is worse than a slowdown: this could
**hard-fail** the parse/embed stage outright on an API validation error for
any sufficiently large document, rather than merely taking longer.

### Resource Impact
Not measured live (no large document was ingested this session to trigger it)
— identified by code inspection and cross-reference with the resolution
path's existing, deliberate batching at the same config knob
(`ARYX_EMBED_BATCH_SIZE`).

### Cost Impact
No dollar cost difference — same total texts embedded either way. The cost is
reliability: an oversized single request either errors immediately or, if
accepted, offers no opportunity to retry a failed sub-range without redoing
the whole document.

### Fix Applied
`embed_chunks()` now batches at `ARYX_EMBED_BATCH_SIZE` (default 50), calling
`broker.embed()` once per batch and concatenating results in original order:
```python
for start in range(0, len(chunks), batch_size):
    batch_vectors = broker.embed([c.text for c in chunks[start:start + batch_size]])
    vectors.extend(batch_vectors)
```
Verified via `tests/test_embed_chunks.py` (5/5 passed): batch-splitting count,
single-batch-under-limit, order-preservation, empty-input, missing-model-config.

**Known issue noted in passing, not fixed:** `broker.embed_model_id` reads a
static value (`"nomic-embed-text"`) from `catalog.json`'s local-Ollama config
regardless of which backend actually served the request. In OCI mode, the
`ChunkEmbedding.model_id` field is written as `"nomic-embed-text"` even though
`cohere.embed-multilingual-v3.0` was the model actually called — a provenance/
metadata correctness issue, not a performance one. Not addressed this session.

### Fix — OCI Path
N/A — same fix applies regardless of backend; the local Ollama path was never
at risk (Ollama has no comparable per-request input cap) but gains the same
consistency from batching.

---

## P12 — Graph Projection: 25-Row Batch Cap on Oracle Writes *(Fixed)*

**Status:** ✅ Fixed 2026-07-27, verified via updated unit tests, deployed to running `api` container.

**Source file:**
- `src/aryx/graph/oracle_graph_store.py` — `_CHUNK_MAX_ROWS = 25`, used by
  `add_entities_batch()`, `add_provenance_batch()`, `add_relationships_batch()`
  via the shared `_iter_chunks()` helper

**What happened — measured live on a full end-to-end ingest (2026-07-27):**
After P8-P11 were all deployed, a full re-run of the same 30-file CPQ workspace
completed in **40m6s** — but **21m55s of that (55%)** was the final graph
projection step alone: 12,244 entity vertices + 60,144 relationship edges,
both written to Oracle ADB in batches of **25 rows per round-trip**.

| Phase | Volume | Round-trips (25/batch) | Duration |
|---|---|---|---|
| Vertices | 12,244 | 490 | 2m9s |
| Edges | 60,144 | 2,406 | ~19m46s (measured rate ~0.26s/round-trip) |

`_CHUNK_MAX_ROWS = 25` was sized as a rough proxy ("num_rows × num_bind_params")
to avoid ORA-03106 (oversized packet) on entity writes carrying large CPQ
attribute JSON blobs — but `_CHUNK_MAX_BYTES = 50_000` already exists as the
real, byte-based guard against exactly that. At 25 rows of typical attrs
(a few hundred bytes), the row cap was the binding constraint almost every
time, not the byte cap — turning every graph write into far more round-trips
to Oracle Cloud than the byte budget actually required.

### Accuracy Impact
**None.** Same vertices/edges written either way, in larger round-trips.

### Resource Impact
This was, by a wide margin, the single largest contributor to total ingest
time in this session's testing — bigger than the original Link-stage bug
(P8) ever was, and bigger than Relate + Resolve + Discover combined.

### Cost Impact
Same total data transferred; the cost was purely round-trip *count*, each one
a real network hop to `adb.us-chicago-1.oraclecloud.com`.

### Fix Applied
Raised `_CHUNK_MAX_ROWS` from 25 to 500. `_CHUNK_MAX_BYTES` (50,000) is
**unchanged** and remains the actual safety net against ORA-03106 — it caps
accumulated bind-value bytes per call regardless of row count, so oversized
CPQ attribute blobs still force an earlier split exactly as before. The row
cap simply no longer triggers before the byte cap would, for typical data.

Also fixed 3 pre-existing stale tests in `tests/test_oracle_pool.py`
(`TestGraphStoreBatchChunking`) that were still asserting a chunk size of
100 from before the constant had already been lowered to 25 — now correctly
assert 500 with volumes that exercise the real boundary (1,250 / 1,050 rows).

**Verified:** `tests/test_oracle_pool.py` — 84/84 passed (previously 3 failing).
Full session suite — **108/108 passed**, first fully green run this session.

**Projected improvement:** at the same measured ~0.26s/round-trip, 500-row
batching turns 2,896 total round-trips (490 + 2,406) into ~26 + ~121 = ~147 —
a ~95% cut, projecting the 21m55s graph-projection stage down to roughly
30-60 seconds.

### Fix — OCI Path
N/A — Oracle-specific implementation detail; the fix is entirely within the
Oracle adapter and has no local-mode equivalent (FalkorDB writes are already
cheap, same-host calls).

---

## P13 — CPQ Product Config Load: Per-Attribute `neighbors()` N+1 *(Fixed)*

**Status:** ✅ Fixed 2026-07-27. Found live while verifying the Ask-thread
Oracle port (see `docs/OCI_POSTGRES_PARITY_AUDIT.md`) — a real CPQ
configuration turn against OCI/ADB never returned within a 180s client
timeout, and a background stale-job sweep then logged
`oracle_pool: connection acquire failed (pool exhausted)`.

**Source files:**
- `src/aryx/cpq/engine.py` — `CpqEngine.load_product_config()` Step 3, the
  `for ent in attr_ents: ... reader.neighbors(eid)` loop
- `src/aryx/graph/oracle_graph_reader.py` — `OracleGraphReader.neighbors()`,
  called once per config-attribute entity
- `src/aryx/ports/protocols.py` — `GraphReaderPort` protocol

**What happened:**
```python
for ent in attr_ents:              # one iteration per bm_config_attr entity
    eid = ent["id"]
    neighbors = reader.neighbors(eid)   # one Oracle round-trip PER ATTRIBUTE
    ...
```
`load_product_config()`'s docstring and an existing code comment already
claimed the N+1 pattern had been eliminated ("Two-pass approach eliminates
both the cap and the N+1 pattern") — that was only true for the relational
attribute/menu-item fetch (already batched via `_batch_fetch`), not for this
graph-side neighbor lookup, which still ran once per entity.

Measured live for workspace 328's `videoSolutions_BOM` product (235
`bm_config_attr` entities):
| Metric | Value |
|---|---|
| `neighbors()` round-trip latency | ~746ms/call (measured, 20-call sample) |
| Config attrs on this product | 235 |
| Projected total time for Step 3 alone | ~175 seconds |
| Client-observed behavior | request never completed within a 180s timeout |

Against FalkorDB (in-process, sub-millisecond Cypher calls) this same loop is
cheap and invisible — the pattern only becomes a real bottleneck once each
round-trip is a genuine network hop to a remote Oracle ADB instance, the same
root cause as P8/P10/P12 above, here in the Ask/CPQ query path instead of
the ingestion pipeline.

### Accuracy Impact
**None.** Same neighbor data either way — pure wasted round-trips, not a
correctness issue. (Two overlapping hung requests did trigger real connection
pool pressure during diagnosis, logged as `pool exhausted`, but that was a
symptom of the slow loop, not a separate leak — `OraclePool.connection()`'s
`finally: self._pool.release(raw)` releases correctly on every path.)

### Resource Impact
The CPQ conversational flow (`/ask` when `is_cpq_question()` triggers, or a
continuing `session_data.mode == "cpq"` turn) never returns in practical terms
for any product with enough config attributes to make ~750ms × N exceed a
caller's timeout — in effect, CPQ mode was non-functional against OCI/ADB for
any real product catalog, only appearing to work in quick manual code-level
checks that never exercised a full conversational turn.

### Fix Applied
Added `neighbors_batch(entity_ids)` to `GraphReaderPort` and both concrete
readers — one query replaces N:
- `OracleGraphReader.neighbors_batch()` — single `UNION ALL` query with two
  `IN (...)` lists (uniquely-numbered named binds throughout, no bind name
  reused across the two SELECT branches — see the `ask_thread_touch_thread.sql`
  precedent for why reused positional/named labels are unsafe with oracledb's
  thin client)
- `GraphReader.neighbors_batch()` (FalkorDB) — single `UNWIND $ids` Cypher
  query, added for interface parity even though FalkorDB's per-call cost was
  never the problem
- `CpqEngine.load_product_config()` Step 3 — one `reader.neighbors_batch(...)`
  call instead of a per-entity loop

Verified live:
- Correctness: `neighbors_batch()` output matched `neighbors()` called
  per-entity for 15 sampled attrs — 0 mismatches.
- Speed: 235-entity batch completed in **14.5s**, down from a ~175s projection
  (~12x faster).
- End-to-end: a real two-turn CPQ conversation against workspace 328
  (`videoSolutions_BOM`) completed in 37s and 82s respectively — session
  state (`session_data`) round-tripped correctly, and rule-driven defaults
  (102 value rules) were applied correctly to real BigMachines attributes.

### Cost Impact
- Before: N Oracle round-trips per CPQ turn (N = config attrs on the
  product) — effectively unusable for products with more than a few dozen
  attributes
- After: 1 round-trip for this step regardless of attribute count

### Fix — OCI Path
N/A — same architectural fix applies to any backend; FalkorDB's cheap
round-trips just never exposed the pattern as a problem the way Oracle
ADB's real network latency did.

---

## P14 — Cross-Tenant Write/Delete: Missing `workspace_id` Scoping *(Fixed)*

**Status:** ✅ Fixed 2026-07-28. Found via a systematic audit of every query
against the 37 Oracle tables carrying a `workspace_id` column, prompted by
the P13 investigation surfacing one such bug (`find_entities()`'s missing
filter, a read-only leak). This audit found three more instances — all
writes/deletes, a more serious class than the read-only one already fixed.

**Source files:**
- `src/aryx/api/datasource_api.py` — `DELETE /admin/datasources/{id}` and
  `POST /admin/datasources/{id}/test`; `src/aryx/store/datasource_store.py`
  — `get()`, `secret_of()`, `delete()`; `select_datasource_by_id.sql`,
  `delete_datasource_row.sql`
- `src/aryx/api/actions_api.py` — `POST /executions/{id}/decide`;
  `src/aryx/store/action_store.py` — `decide()`, `record_applied()`,
  `execution()`; `decide_action_execution.sql`, `apply_action_execution.sql`,
  `select_action_execution_by_id.sql`
- `src/aryx/api/relationship_type_api.py` — `DELETE /ontology/relationships/{id}`;
  `src/aryx/store/relationship_type_store.py` — `delete()`;
  `delete_relationship_type.sql`

**What happened:**
```sql
-- delete_datasource_row.sql, before:
DELETE FROM aryx_datasource WHERE id = %(id)s
```
Each of these deleted or mutated a row by its raw integer primary key alone
— no `workspace_id` check anywhere in the SQL, the store method, or (for
`datasource_api.py`) even in the route signature. All three underlying
tables use `NUMBER GENERATED ALWAYS AS IDENTITY` — plain sequential integer
IDs, enumerable across every workspace sharing the database. A caller
supplying their own valid `workspace_id` alongside a *different* workspace's
sequential ID could delete another workspace's datasource, or approve/
reject/apply another workspace's pending action execution.

For `ActionStore` specifically, the bug was a real inconsistency rather than
an oversight repeated three times identically: the class already carries
`self._ws` (used correctly by `select_action_executions`), but `decide()`,
`record_applied()`, and `execution()` simply never referenced it.

### Accuracy Impact
**None** for legitimate same-workspace use — same rows read/written either
way. The impact is a real cross-tenant integrity/security gap, not a
correctness bug for the honest path.

### Resource Impact
N/A — this is a security/isolation gap, not a performance issue.

### Cost Impact
Not dollar-denominated — the risk is unauthorized cross-workspace deletes or
action approvals, not spend.

### Fix Applied
Added `workspace_id` to every affected SQL statement's `WHERE` clause,
threaded it through each store method's signature, and (for
`datasource_api.py`, the only router missing it entirely) added it to the
route signatures. `ActionStore`'s three methods now use the `self._ws` the
class already carried — no route changes needed there, since
`actions_api.py` already built a workspace-scoped store instance.

**Verified live against real ADB**, not just unit tests: created a
datasource in workspace 342, confirmed workspace 274 gets a clean 404 on
test/get, confirmed a delete call from workspace 274 is silently a no-op
(the real owner could still fetch the row immediately after), and confirmed
only the real owner's delete actually removed it. Existing
`tests/test_datasource_store.py` (8/8) still passes.

### Fix — OCI Path
N/A — the same fix applies identically to Postgres; nothing here is
Oracle-specific. (Separately, `docs/OCI_ADB_NATIVE_AI_FEATURES_ANALYSIS.md`
Part 4 proposes Oracle VPD/Row-Level Security as defense-in-depth against
this exact bug *class* recurring in future code — not yet implemented.)

---

## P15 — Discovery Summary/Confirm: Full-Payload Deserialization for a Small Read *(Fixed)*

**Status:** ✅ Fixed 2026-07-28. Found live while diagnosing a real user
report: "read/discover completed but there's no way to hit confirm — I'm
not seeing the button."

**Source files:**
- `src/aryx/store/discovery_store.py` — `DiscoveryStore.get()` /
  new `get_summary()`
- `src/aryx/discoveries.py` — `get()` / new `get_summary()`
- `src/aryx/api/doc_discover_api.py` — `GET /admin/docs/summary/{did}`,
  `POST /admin/docs/confirm`
- `select_discovery.sql`, new `select_discovery_summary.sql`

**What happened:**
`aryx_discovery.data_json` stores the *entire* raw discovery payload —
every uploaded file's bytes, base64-encoded, plus extracted mentions — as
one CLOB. For a real 30-file customer discovery, that CLOB measured
**257 MB**. Both `GET /admin/docs/summary/{did}` (loads the review-step
checklist) and `POST /admin/docs/confirm` (the existence/ownership check
before queuing the ingest job) called `discoveries.get()`, which
unconditionally fetches and fully JSON-deserializes `data_json` — via a
custom `object_hook` doing per-object Pydantic/bytes reconstruction, slower
than plain `json.loads()` — just to read the separate, small `summary_json`
field, or just to confirm the row exists.

Measured live, same discovery, before the fix:
| Call | Time |
|---|---|
| `GET /admin/docs/summary/{did}` | **246.4 s** |
| Summary content actually needed | `{"types": [], "files": [...30 entries...]}` — a few KB |

246 seconds is far beyond any browser fetch timeout a user would wait out —
the review step's "Confirm & ingest" button never had a chance to render;
from the user's side this looked exactly like a broken/missing button, with
no error shown (the request was still in flight, not rejected).

### Accuracy Impact
**None.** Same summary content either way — pure wasted deserialization.

### Resource Impact
Before the fix, **any workspace with a multi-file (or otherwise large)
pending discovery had a non-functional confirm flow** — not slow, but
effectively broken past a certain payload size, since no realistic client
timeout would wait 246+ seconds.

### Cost Impact
No dollar cost — CPU/wall-clock only, but the practical cost was a fully
blocked feature for any sufficiently large discovery.

### Fix Applied
Added `DiscoveryStore.get_summary()` / `discoveries.get_summary()`, backed
by a new `select_discovery_summary.sql` selecting *only* `summary_json` —
skipping `data_json` (and `confirm_state`) entirely. Both the summary
endpoint and the confirm endpoint's existence check now use this lightweight
path; the full `discoveries.get()` remains only inside `_confirm_job()`'s
background task, where the raw file data is genuinely required to actually
perform ingestion.

**Verified live, same 257MB discovery, before/after:** 246.4s → **2.7s**
(~91x faster), identical 30-file summary content returned. Existing
`tests/test_discovery_store.py` (11/11) still passes.

**Known limitation, not fixed:** `_confirm_job()`'s own initial
`discoveries.get()` call still pays the full ~4-minute deserialization cost
once, at the very start of the background ingest job, before any progress
appears — confirmed live on the same discovery (job showed "queued" for
~4 minutes before its first real stage update). This is unavoidable within
the current storage design, since the confirm job genuinely needs the raw
file bytes/mentions, not just the summary. A real fix would mean splitting
`data_json` storage (e.g., per-file rows instead of one giant blob per
discovery) — a materially bigger change than today's fix, not undertaken
here.

### Fix — OCI Path
N/A — same fix applies identically to Postgres; the bug was in the query
shape (fetching two columns to read one), not anything Oracle-specific.

---

## P16 — Oracle `RETURNING...INTO` Size Limit on JSON Columns *(Fixed)*

**Status:** ✅ Fixed 2026-07-28. Found live during the very next attempt to
confirm the same real customer discovery, immediately after P15 was fixed
and deployed — the confirm job progressed further than ever before, then
failed with a new, previously-unseen error.

**Source files:**
- `insert_datasource.sql`, `update_datasource.sql`
- `src/aryx/store/datasource_store.py` — `add()`, `update()`

**What happened:**
```
ORA-40478: output value too large (maximum: 16386)
JZN-00018: Input to serializer is too large
```
Confirming the discovery registers each source file as a datasource catalog
entry (`upsert_xml_catalog_entry` → `DatasourceStore.add()`). The INSERT's
`RETURNING` clause included `config_json` — a native Oracle `JSON` column.
Oracle enforces a hard ~16KB limit specifically on `RETURNING ... INTO` for
JSON columns (a documented Oracle limitation, distinct from and much smaller
than ordinary CLOB/LOB limits), regardless of how large a JSON column can
actually store. The SVX catalog's `config_json` (listing all its ingested
assets) exceeded that, so the INSERT itself would have succeeded, but
handing the value back through `RETURNING` failed outright.

### Accuracy Impact
**None once fixed.** Same row written either way; the bug only affected the
value handed back to the caller, not what was persisted.

### Resource Impact
Before the fix, **any XML/multi-asset source whose catalog config exceeded
~16KB could never be confirmed at all** — not slow, a hard failure on every
attempt, for any discovery with enough assets in one source file.

### Cost Impact
No dollar cost — a correctness/availability issue, not a spend issue.

### Fix Applied
Dropped `config_json` from both `insert_datasource.sql`'s and
`update_datasource.sql`'s `RETURNING` clauses. The caller already has the
`config` dict in Python (it's what was just inserted/updated) — no need to
round-trip it through Oracle at all. `DatasourceStore.add()`/`update()` now
build their returned dict from the caller-supplied `config` plus the
remaining (small, scalar) `RETURNING` columns.

**Verified live:** reproduced the exact failure with a 151,792-byte config
(far past the ~16KB limit) — insert now succeeds and returns correct data.
Existing `tests/test_datasource_store.py` (8/8) still passes. Confirmed
end-to-end: the real customer discovery's confirm job proceeded past this
point on retry.

### Fix — OCI Path
N/A — Oracle-specific by nature (the limit itself is an Oracle `RETURNING`
behavior; Postgres has no equivalent restriction and was never affected).

---

## P17 — Schema-FK LLM Inference: Sequential Batches *(Identified, Not Fixed)*

**Status:** 🟡 Identified 2026-07-28, not yet fixed. Found by timing the real
30-file SVX confirm job (P14-P16's fix verification) end to end and breaking
down exactly where its 40m56s went.

**Source file:** `src/aryx/pipeline/enrich.py` — `_infer_schema_fk_links()`

**Full timing breakdown of the real confirm job (40m56s total):**

| Phase | Duration | % of total |
|---|---|---|
| Initial full-payload fetch (P15's known remaining cost) | ~3m57s | 10% |
| Discover+Resolve+Seed+Relate (30 files) | ~16m43s | 41% |
| Schema-FK LLM inference (5 batches) | ~8m7s | 20% |
| Deterministic FK-edge linking (54 specs) | ~2m29s | 6% |
| Graph Project — vertices (12,244 rows) | ~2m37s | 6% |
| Graph Project — provenance (12,246 rows) | ~1m28s | 4% |
| Graph Project — edges (56,416 rows) | ~3m24s | 8% |
| Final wrap-up | ~12s | <1% |

**The striking part:** this is nearly the same *total* time as the pre-fix
baseline in P8-P12 (40m6s, same-sized workspace) — but the composition
completely inverted. That baseline was 55% graph projection (the P12 bug,
now fixed to ~18% combined here). Nothing got newly slow — fixing the
biggest bottleneck just stopped hiding the next ones. Discover/Resolve/Seed/
Relate and schema-FK LLM inference were always this expensive; they're only
now the visible cost.

**What happened in schema-FK inference specifically:**
```python
for batch_types in batches:
    batch_keys = [anchor_type] + batch_types
    batch_schemas = {t: type_schemas[t] for t in batch_keys if t in type_schemas}
    try:
        links = infer_fk_links(batch_schemas, broker)   # one blocking LLM call
    except Exception:
        logger.exception(...)
        continue
    for lnk in links:
        ...  # dedup into `seen`, order-independent
```
Five batches, run one after another, each a separate blocking
`complete_json()` call. They're fully independent — different, non-
overlapping type subsets, deduplicated into one `seen` set afterward
regardless of completion order — so nothing requires them to run
sequentially. Measured live: batch timings were highly uneven (one single
batch took **4m6s** by itself — more than half of the entire 8m7s phase),
consistent with ordinary LLM response-time variance rather than anything
input-size-dependent. Running all 5 concurrently would let the phase's
wall-clock time collapse to roughly the *slowest single batch* instead of
the *sum* of all batches — a potential ~5-8x cut to this specific phase,
similar in shape to P9's serial-LLM-call fix, but via concurrency rather
than threshold tuning (this batching genuinely needs the LLM, unlike P9's
adjudication calls which had a non-LLM fallback).

### Accuracy Impact
None — same links inferred either way, only wall-clock time would change.

### Resource Impact
~8 minutes of the ~41-minute confirm job, for this specific dataset
(depends on how many entity types share a workspace — more types means
more batches means more to parallelize).

### Cost Impact
No change in LLM $ cost — same number of calls either way, just concurrent
instead of sequential.

### Proposed Fix (not yet applied)
Replace the sequential `for` loop with a concurrent dispatch (e.g.
`ThreadPoolExecutor`, already used elsewhere in this codebase per P4) over
independent batches, collecting results into the same `seen`-deduplicated
list once all complete. Not implemented yet — flagged for a decision on
whether the added complexity (thread safety around the shared `broker`
client, potential provider-side rate limiting from concurrent calls) is
worth it given the pipeline already completes successfully today, just
takes longer than it could.

### Fix — OCI Path
N/A — same fix applies regardless of backend; this is Python-side
orchestration around the LLM call, not anything Oracle- or Postgres-specific.

---

## P18 — Cross-Tenant Adjudication Decide: Missing `workspace_id` Scoping *(Fixed)*

**Status:** ✅ Fixed 2026-07-28. Found via a self-review sweep after P14,
specifically checking every store class that carries `self._ws` for methods
that don't actually use it — the same shape of audit that found P14, applied
more broadly this time.

**Source files:**
- `src/aryx/api/adjudication_api.py` — `POST /adjudication/{id}/decide`
- `src/aryx/store/adjudication_store.py` — `decide()`
- `decide_adjudication.sql`

**What happened:**
`AdjudicationStore` carries `self._ws` and uses it correctly in `enqueue()`,
`page()`, `stats()`, and `merge_entities_of()` — but `decide()` never
referenced it, the exact same inconsistency P14 found in `ActionStore`.
```sql
-- before:
UPDATE aryx_adjudication SET status = %s, ... WHERE id = %s AND status = 'pending'
```
`aryx_adjudication.id` is `NUMBER GENERATED ALWAYS AS IDENTITY` — sequential
and enumerable across workspaces, same exploit shape as P14. The API route
(`adjudication_api.py`) already builds a workspace-scoped store, so a caller
supplying their own `workspace_id` alongside a *different* workspace's
sequential `adjudication_id` could approve or reject another workspace's
pending entity-merge decision — and approval triggers `merge_entities_of()`,
so this could actually merge entities in a workspace the caller doesn't own.

### Accuracy Impact
None for legitimate same-workspace use. Real cross-tenant integrity gap for
the dishonest path, same as P14.

### Resource Impact
N/A — security/isolation gap, not a performance issue.

### Cost Impact
Not dollar-denominated — risk is unauthorized cross-workspace entity merges
or adjudication decisions.

### Fix Applied
Added `workspace_id` to `decide_adjudication.sql`'s `WHERE` clause and
threaded `self._ws` through `AdjudicationStore.decide()` — no route or
signature changes needed, since `adjudication_api.py` already built a
workspace-scoped store instance.

**Verified live against real ADB**: enqueued a synthetic adjudication row in
workspace 342, confirmed a decide attempt from workspace 274 fails with
`ValueError: adjudication {id} not pending` (the `UPDATE` matched zero rows
due to the workspace mismatch), then confirmed the real owner's decide call
succeeded normally. Existing `tests/test_adjudication.py` (8/10 — 2
pre-existing unrelated failures in `resolution/run.py` return-value naming,
confirmed unrelated: no reference to `decide()` or `workspace_id` in either
failing test) still passes at the same rate.

**Also checked and ruled out during the same sweep:** every other store
class carrying `self._ws` (`EntityStore`, `ChunkBackend`, `PostgresStore`,
`ProjectionStore`, `SourceMetricsStore`) — spot-checked the highest-risk
methods (get/update/delete-by-id) and confirmed they all correctly pass
`self._ws`. `AdjudicationStore.decide()` was the only other instance found
beyond the three P14 already fixed.

### Fix — OCI Path
N/A — same fix applies identically to Postgres, nothing here is
Oracle-specific.

---

## Summary — Fix Priority & OCI Readiness

| # | Bottleneck | Accuracy loss | Resource loss | Fix complexity | OCI required? |
|---|---|---|---|---|---|
| P1 | fetchall RAM spike | None | ✅ Fixed | Already done | No |
| P2 | Rule evaluator loop | Minor improvement | 🔴 API blocks | Low — 1 file + 1 SQL | No |
| P3 | Block silent drop | 🔴 Direct data loss | Low | Medium | No |
| P4 | Single worker | None | 🟡 Throughput cap | Medium | No |
| P5 | Query cap 500 | 🟡 Incomplete Ask | Low | Low — add pagination | No |
| P6 | Relate cap 50 | 🟡 Sparse relations | Intentional (cost) | Low | No (OCI lowers cost) |
| P7 | Transitive cap 4 | 🟡 Deep hierarchy miss | Low | Low — raise constant | No |
| P8 | Schema-FK per-spec refetch | ✅ Fixed | 🔴 Was 25-40 min stage → ~90% reduction | Low — 4 call sites | No |
| P9 | Adjudication serial LLM calls | ✅ Fixed | 🟡 Was multi-minute serial calls | Low — env config | No (already OCI) |
| P10 | Chunk/embedding N+1 writes | ✅ Fixed | 🟡 Was ~400 round-trips/doc → ~3 | Low — 1 file + 2 SQL | No (already OCI) |
| P11 | Embed calls unbatched | ✅ Fixed | 🔴 Was potential hard-fail on large docs | Low — 1 file | No (already OCI) |
| P12 | Graph write 25-row cap | ✅ Fixed | 🔴 Was 21m55s of a 40m6s total run (55%) | Low — 1 constant + tests | No (already OCI) |
| P13 | CPQ config load N+1 `neighbors()` | ✅ Fixed | 🔴 Was effectively non-functional for real products | Low — 1 method × 2 backends + 1 call site | No (already OCI) |
| P14 | Missing `workspace_id` on writes/deletes | ✅ Fixed | 🔴 Was a real cross-tenant delete/write gap, 3 endpoints | Low — SQL + store + route changes | No |
| P15 | Discovery summary full-payload deserialize | ✅ Fixed | 🔴 Was non-functional (246s) for large discoveries → 2.7s | Low — 1 SQL + 2 methods + 1 call site | No |
| P16 | Oracle `RETURNING` 16KB JSON limit | ✅ Fixed | 🔴 Was a hard failure on any large datasource config | Low — 2 SQL files + 2 methods | No — Oracle-only bug |
| P17 | Schema-FK LLM sequential batches | Not fixed | 🟡 ~8 of ~41 min in one confirm job; one batch alone 4m6s | Medium — concurrency + thread-safety review | No |
| P18 | Missing `workspace_id` on adjudication decide | ✅ Fixed | 🔴 Was a real cross-tenant entity-merge approval gap | Low — 1 SQL file + 1 method | No |

**P3 is now the most urgent unfixed risk** — silent data loss with no visible
error. P1 was believed to be the other urgent unfixed risk (OOM at scale) but
was confirmed already fixed in code during the 2026-07-27 sweep.

**P8-P12 were all found and fixed during a live OCI-mode ingest investigation
(2026-07-27)**, culminating in a full measured end-to-end run: 40m6s total,
with **P12 (graph projection) the single largest cost at 55% of total time**
— larger than P8 (Link stage) ever was, larger than Resolve+Relate+Discover
combined. P11 was a latent reliability risk (potential hard failure on large
documents) rather than a measured slowdown.

**P14-P16 were all found and fixed during a live end-to-end confirm-flow
investigation (2026-07-28)**, triggered by a real user report that document
ingestion's "Confirm" button appeared broken. P14 was found by a proactive
audit prompted by P13's discovery of a similar (read-only) gap; P15 and P16
were each found live, one immediately after the other, by actually retrying
the same real customer discovery through to completion rather than stopping
once the first fix appeared to work.

**P17 was identified, and P18 found and fixed, during a post-implementation
self-review (2026-07-28)** asked for explicitly after P14-P16 shipped —
P18 is the same cross-tenant scoping bug class as P14, found by sweeping
every store class carrying `self._ws` for methods that don't actually use
it, rather than assuming the P14 audit's three instances were exhaustive.

All fixes except P6 can be implemented today without OCI. OCI improves
each fix but is not required for the initial scale improvements.

---

## OCI Migration Impact on Each Bottleneck

| Bottleneck | After OCI Migration | Remaining limit |
|---|---|---|
| P1 — RAM spike | 0 MB Python RAM (streaming cursor, Oracle ADB) | None |
| P2 — Rule loop | 0 Python iterations (PGX graph engine) | None |
| P3 — Block drop | Distributed comparison via OCI Data Flow | None |
| P4 — Single worker | Parallel Spark jobs via OCI Data Flow | Cost (pay per job) |
| P5 — Query cap | No cap (Oracle Spatial & Graph PGQL) | None |
| P6 — Relate cap | Structural relations via PGX axioms (free) | LLM semantic pairs still capped |
| P7 — Transitive cap | Unbounded (owl:TransitiveProperty via PGX) | None |
| P8 — Schema-FK refetch | N/A — Python-side fix, backend-independent | None once fixed |
| P9 — Adjudication LLM calls | Already OCI GenAI; threshold tuning applied | Fewer LLM-adjudicated matches (precision/recall trade) |
| P10 — Chunk/embedding N+1 | Already OCI ADB; batching applied | None |
| P11 — Embed calls unbatched | Already OCI GenAI; batching applied | Model-id provenance still wrong for OCI embeds (unfixed) |
| P12 — Graph write 25-row cap | Oracle-specific fix, already applied | None — byte cap remains the real ORA-03106 guard |
| P13 — CPQ config load N+1 | Batched `neighbors_batch()`, already applied | None — same fix works identically on FalkorDB |
| P14 — Missing workspace_id scoping | N/A — Python/SQL-side fix, backend-independent | None once fixed |
| P15 — Discovery summary full deserialize | N/A — query-shape fix, backend-independent | Confirm job's own initial full-fetch still costs ~4 min for very large discoveries (unfixed) |
| P16 — Oracle RETURNING 16KB JSON limit | Oracle-specific fix, already applied | None — Postgres was never affected |
| P17 — Schema-FK LLM sequential batches | N/A — same fix applies regardless of backend | Not yet fixed |
| P18 — Missing workspace_id on adjudication decide | N/A — Python/SQL-side fix, backend-independent | None once fixed |

---

## Measured End-to-End Result (2026-07-27)

Full re-run of the same 30-file CPQ workspace (12,244 entities, 60,144
relationships) after P8-P11 were deployed, P12 not yet applied at run time:

| Stage | Duration | % of total |
|---|---|---|
| Discover→Resolve→Seed→Project (30 files) | 8m28s | 21% |
| Relate (100 pairs) | 3m46s | 9% |
| Link — schema_fk (48 specs) | 5m10s | 13% |
| Link — fk_link (48 specs, cached entities) | 48s | 2% |
| Graph projection (vertices+edges, pre-P12) | 21m55s | 55% |
| **Total** | **40m6s** | |

With P12 applied (projected, ~95% cut to the graph-projection stage): total
should land around **~19-20 minutes** for this same workload — down from a
run that, before this session's fixes, never completed (2h43m timeout).

---

*Generated: 2026-06-18 | aryx project | giggso*
*Updated: 2026-07-27 — added P8-P12, all found and fixed during a live*
*OCI-mode ingest investigation, including one full measured end-to-end run*
*Updated: 2026-07-27 — added P13, found and fixed while live-verifying the*
*Ask-thread Oracle port's CPQ conversation flow*
*Updated: 2026-07-28 — added P14-P16, found and fixed during a live*
*document-ingestion confirm-flow investigation triggered by a real user*
*report, verified end to end against a real 30-file customer discovery*
*Updated: 2026-07-28 — added P17, identified by timing that same real*
*confirm job's full 40m56s end-to-end run; not yet fixed*
*Updated: 2026-07-28 — added P18, found and fixed during a post-*
*implementation self-review of P14-P17 requested explicitly; same*
*cross-tenant scoping bug class as P14, in AdjudicationStore.decide()*
*Source analysis: src/aryx/store/entity_store.py, src/aryx/reasoning/engine.py,*
*src/aryx/resolution/blocking.py, src/aryx/graph/reader.py, src/aryx/pipeline/orchestrate.py,*
*src/aryx/pipeline/fk_edges.py, src/aryx/resolution/run.py, src/aryx/resolution/adjudicate.py,*
*src/aryx/store/chunk_store.py, src/aryx/pipeline/embed.py, src/aryx/broker/__init__.py,*
*src/aryx/api/data_api.py, src/aryx/api/workspace_api.py, src/aryx/graph/oracle_graph_store.py,*
*src/aryx/cpq/engine.py, src/aryx/graph/oracle_graph_reader.py, src/aryx/ports/protocols.py,*
*src/aryx/store/datasource_store.py, src/aryx/store/action_store.py,*
*src/aryx/store/relationship_type_store.py, src/aryx/store/discovery_store.py,*
*src/aryx/discoveries.py, src/aryx/api/doc_discover_api.py,*
*src/aryx/pipeline/enrich.py, src/aryx/relationships.py,*
*src/aryx/store/adjudication_store.py, src/aryx/api/adjudication_api.py*
