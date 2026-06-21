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
| P1 | 🔴 Critical | Graph projection — `fetchall()` | >500K entities |
| P2 | 🔴 Critical | Rule evaluator — Python loop | >100K entities × rules |
| P3 | 🟡 High | Resolution blocking — silent drop | Blocks >5,000 records |
| P4 | 🟡 High | Single-threaded pipeline worker | Large file batches |
| P5 | 🟢 Medium | FalkorDB query hard cap | >500 entity results |
| P6 | 🟢 Medium | Relationship inference cap | >50 entity pairs |
| P7 | 🟢 Medium | Transitive closure cap | Hierarchies >4 hops deep |

---

## P1 — Graph Projection `fetchall()` Memory Spike

**Source files:**
- `src/aryx/store/entity_store.py:105` — `list_entities()` → `fetchall()`
- `src/aryx/store/entity_store.py:112` — `list_members_provenance()` → `fetchall()`
- `src/aryx/store/entity_store.py:119` — `list_relationships()` → `fetchall()`
- `src/aryx/project.py:52` — calls all three before touching FalkorDB

**What happens:**
```python
entities = store.list_entities()       # entire aryx_entity table → Python list
provenance = store.list_members_provenance()   # entire provenance → Python list
relationships = store.list_relationships()     # entire relationships → Python list
```
All three tables are loaded into Python memory simultaneously before a single
node is written to FalkorDB.

### Accuracy Impact
**None.** Streaming reads identical rows in identical order.
Result set is byte-for-byte the same — only memory footprint changes.

### Resource Impact
| Dataset size | RAM spike (Python) | Projection time |
|---|---|---|
| 100K entities | ~50 MB | ~2 min |
| 500K entities | ~250 MB | ~10 min |
| 1M entities | ~500 MB | ~20 min |
| 5M entities | ~2.5 GB | OOM crash |

On the recommended 16 GB VM, OOM occurs at approximately 3M entities
depending on attribute payload size.

### Cost Impact
- On 16 GB VM: free until OOM, then pipeline crash = re-run cost
- Re-run of a 1M entity projection: ~20 min compute × worker cost
- OCI A1.Flex 4 OCPU: ~$0.01/hr → negligible per run, significant at scale with retries

### Fix — Today (no OCI required)
Replace `fetchall()` with a named server-side streaming cursor:

```python
def iter_entities(self, batch_size: int = 1000):
    with self._pool.connection() as conn:
        with conn.cursor("entity_cursor") as cur:  # named = server-side
            cur.execute(load("select_entities"), (self._ws,))
            while True:
                rows = cur.fetchmany(batch_size)
                if not rows:
                    break
                yield from ((r[0], r[1], r[2]) for r in rows)
```

RAM drops from 500 MB spike → 5 MB constant regardless of dataset size.

### Fix — OCI Path
Oracle Autonomous Database (RelationalPort adapter) supports the identical
named cursor pattern. Zero code change at the call-site — only the adapter
class changes via env var.

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

## Summary — Fix Priority & OCI Readiness

| # | Bottleneck | Accuracy loss | Resource loss | Fix complexity | OCI required? |
|---|---|---|---|---|---|
| P1 | fetchall RAM spike | None | 🔴 OOM at 3M+ | Low — 1 file | No |
| P2 | Rule evaluator loop | Minor improvement | 🔴 API blocks | Low — 1 file + 1 SQL | No |
| P3 | Block silent drop | 🔴 Direct data loss | Low | Medium | No |
| P4 | Single worker | None | 🟡 Throughput cap | Medium | No |
| P5 | Query cap 500 | 🟡 Incomplete Ask | Low | Low — add pagination | No |
| P6 | Relate cap 50 | 🟡 Sparse relations | Intentional (cost) | Low | No (OCI lowers cost) |
| P7 | Transitive cap 4 | 🟡 Deep hierarchy miss | Low | Low — raise constant | No |

**P1 and P3 are the most urgent.** P1 causes OOM crashes at scale.
P3 silently loses data with no visible error.

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

---

*Generated: 2026-06-18 | aryx project | giggso*
*Source analysis: src/aryx/store/entity_store.py, src/aryx/reasoning/engine.py,*
*src/aryx/resolution/blocking.py, src/aryx/graph/reader.py, src/aryx/pipeline/orchestrate.py*
