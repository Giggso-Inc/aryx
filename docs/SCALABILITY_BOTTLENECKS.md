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

**P3 is now the most urgent unfixed risk** — silent data loss with no visible
error. P1 was believed to be the other urgent unfixed risk (OOM at scale) but
was confirmed already fixed in code during the 2026-07-27 sweep.

**P8-P12 were all found and fixed during a live OCI-mode ingest investigation
(2026-07-27)**, culminating in a full measured end-to-end run: 40m6s total,
with **P12 (graph projection) the single largest cost at 55% of total time**
— larger than P8 (Link stage) ever was, larger than Resolve+Relate+Discover
combined. P11 was a latent reliability risk (potential hard failure on large
documents) rather than a measured slowdown.

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
*Source analysis: src/aryx/store/entity_store.py, src/aryx/reasoning/engine.py,*
*src/aryx/resolution/blocking.py, src/aryx/graph/reader.py, src/aryx/pipeline/orchestrate.py,*
*src/aryx/pipeline/fk_edges.py, src/aryx/resolution/run.py, src/aryx/resolution/adjudicate.py,*
*src/aryx/store/chunk_store.py, src/aryx/pipeline/embed.py, src/aryx/broker/__init__.py,*
*src/aryx/api/data_api.py, src/aryx/api/workspace_api.py, src/aryx/graph/oracle_graph_store.py,*
*src/aryx/cpq/engine.py, src/aryx/graph/oracle_graph_reader.py, src/aryx/ports/protocols.py*
