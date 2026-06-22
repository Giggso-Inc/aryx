# PR — feat/scalability-bottleneck-fixes

## Summary

Closes three tracked tickets:
- **[#7681](https://odoo.giggso.com/odoo/action-412/66/tasks/7681)** — Bottleneck using hardcoded cap needs to be resolved
- **[#7680](https://odoo.giggso.com/odoo/action-412/66/tasks/7680)** — Documenting the bottlenecks in aryx
- **[#7679](https://odoo.giggso.com/odoo/action-412/66/tasks/7679)** — Bottleneck in aryx flow related to FalkorDB

---

## Problem

Seven independent scalability bottlenecks existed in the aryx pipeline, documented in `docs/SCALABILITY_BOTTLENECKS.md`:

| ID | Location | Problem |
|----|----------|---------|
| P1 | `entity_store.py` | `fetchall()` loads entire entity table into RAM — O(dataset) memory |
| P2 | `reasoning/engine.py` | Rule evaluator ran O(rules × all_entities) Python loop with full table scan |
| P3 | `resolution/blocking.py` | `max_block_size=5000` hardcoded — no way to tune without a code change |
| P4 | `api/file_ingest_api.py` | `BackgroundTasks.add_task()` is single-threaded — files queued serially |
| P5 | `graph/reader.py` | `LIMIT 500` hardcoded in FalkorDB Cypher query |
| P6 | `pipeline/orchestrate.py` | `max_pairs=50` hardcoded for relationship inference |
| P7 | `reasoning/edge_axioms.py` | `_TRANSITIVE_MAX = 4` module constant — no runtime control |

---

## Root Cause

All seven caps were hardcoded integers with no environment-variable override path. The rule evaluator (P2) compounded the issue by calling `list_entities()` — a full table load — once before filtering in Python, wasting RAM and CPU even when only 1% of entities matched a rule. `list_entities()` itself used `cursor.fetchall()` (P1), loading the entire result set into Python memory in a single round-trip.

---

## Fixes

### P1 — True O(batch) streaming via generators (`entity_store.py`)

Converted `list_entities()`, `list_members_provenance()`, `list_relationships()`, and `match_entities()` from list-returning functions to Python generators (`Iterator`). Combined with the existing named psycopg3 server-side cursors + `fetchmany(batch_size)`:

- **Postgres server**: never materialises the full result set (named cursor prevents server-side buffering)
- **Python application**: only one batch is held in memory at a time — true O(batch_size) application memory

Callers that need full-list semantics (`fk_edges.py`, `enrich.py`, `ontology_api.py`, `explore.py`) now materialise explicitly with `list()` at their call sites, making the cost visible. Callers that iterate only once (`engine.py` via `match_entities`, `project.py` graph projection, `axiom_validator.py`) get the full O(batch) benefit.

Cursor names include a `uuid4` short token to prevent name collision under concurrent queries.

### P2 — SQL pushdown for rule evaluator (`engine.py`, `entity_store.py`)

Added `match_entities(when: dict) -> Iterator[dict]` method backed by `select_entities_matching.sql`. Pushes `ontology_type` equality and `attributes ? key` (JSONB key-existence) into Postgres. Rules without `attr` now short-circuit immediately with a `logger.warning()` — no full-table scan, and the rule author gets observability on the misconfigured rule.

### P3 — Configurable block size (`config.py`, `blocking.py`)

`max_block_size` moved to `Settings` as `ARYX_MAX_BLOCK_SIZE` (default 5000).

### P4 — ThreadPoolExecutor for concurrent ingestion (`file_ingest_api.py`)

Replaced `BackgroundTasks.add_task()` with a lazy `ThreadPoolExecutor` singleton sized by `ARYX_WORKER_THREADS` (default 4). Protected by `threading.Lock()` (double-checked locking) to prevent double-initialisation race. Lost background exceptions are caught via `future.add_done_callback()` and logged. `_run_files()` initialises `jobs=None` before the try block so a `JobStore()` failure cannot cause `NameError` in `except`/`finally`.

### P5 — Configurable FalkorDB query limit (`graph/reader.py`)

`LIMIT 500` hardcode replaced with `ARYX_GRAPH_QUERY_LIMIT` (default 500).

### P6 — Configurable relate pairs cap (`pipeline/orchestrate.py`)

`max_pairs=50` default replaced with `ARYX_MAX_RELATE_PAIRS` (default 50).

### P7 — Configurable transitive closure depth (`reasoning/edge_axioms.py`)

`_TRANSITIVE_MAX = 4` removed; replaced with `ARYX_TRANSITIVE_MAX_DEPTH` (default 4).

### Config (`config.py`, `.env.example`)

Five new `Settings` fields with `ARYX_` prefix:

```env
ARYX_MAX_BLOCK_SIZE=5000        # Resolution: max records per blocking group
ARYX_GRAPH_QUERY_LIMIT=500      # Graph: max entities per FalkorDB query
ARYX_MAX_RELATE_PAIRS=50        # Pipeline: max entity pairs for relationship inference
ARYX_TRANSITIVE_MAX_DEPTH=4     # Reasoning: max transitive closure hops
ARYX_WORKER_THREADS=4           # Ingestion: concurrent pipeline workers
```

### Connection pool thread-safety (`store/pool.py`)

`get_pool()` now uses double-checked locking — `ConnectionPool()` releases the GIL during connect, making the bare check-then-create non-atomic. `close_all()` acquires the same lock before snapshotting and clearing `_pools`, eliminating the shutdown race window.

---

## Raven Review Passes

Three code-review passes were run before this PR was marked ready:

| Pass | Verdict | Issues found | Issues fixed |
|------|---------|--------------|--------------|
| First | FAIL | B1 (executor lock), B2 (lost exceptions), B3 (NameError in finally), W1–W5 | All fixed |
| Second | FAIL | B4 (NameError in `_run_files`), W6–W10, INFO x3 | All fixed |
| Third | **PASS** | W11 (silent rule skip), W12 (redundant guard), INFO x2 | All fixed |

---

## Files Changed

**Source — 12 files:**

| File | Change |
|------|--------|
| `src/aryx/config.py` | 5 new config fields |
| `src/aryx/store/entity_store.py` | Streaming cursors + uuid cursor names + `match_entities()` |
| `src/aryx/store/pool.py` | Double-checked locking in `get_pool()`; `close_all()` lock-guarded |
| `src/aryx/queries/select_entities_matching.sql` | New SQL for P2 pushdown |
| `src/aryx/reasoning/engine.py` | Per-rule SQL pushdown; dict entity fix; W11 warning log; Cypher injection guard |
| `src/aryx/reasoning/edge_axioms.py` | `transitive_max_depth` from config |
| `src/aryx/resolution/blocking.py` | `max_block_size` from config |
| `src/aryx/resolution/classical.py` | Delegate `None` to `MultiKeyBlocker` |
| `src/aryx/graph/reader.py` | `graph_query_limit` from config |
| `src/aryx/pipeline/orchestrate.py` | `max_relate_pairs` from config |
| `src/aryx/api/file_ingest_api.py` | ThreadPoolExecutor; lock; done-callback; B4 guard; import order |
| `.env.example` | 5 new documented env vars |

**Tests — 1 file:**

- `tests/test_scalability_fixes.py` — 44 unit tests; all pass without a real DB/FalkorDB connection

---

## Test Plan

```bash
PYTHONPATH=src python -m pytest tests/test_scalability_fixes.py -v
# → 44/44 passed in 0.83s
```

- [x] Config fields: correct defaults; all 5 `ARYX_*` env vars override correctly
- [x] `list_entities()` uses `fetchmany`, never `fetchall`; batches across pages
- [x] Cursor names include workspace id + uuid8 token (collision-safe)
- [x] `match_entities()` returns `list[dict]`; type and attr params pushed to SQL
- [x] Engine calls `match_entities()` per rule; never calls `list_entities()`
- [x] Rules without `attr` short-circuit immediately (W10) — no full table scan
- [x] `MultiKeyBlocker` reads `max_block_size` from config; explicit arg still overrides
- [x] `_get_executor()` sized by `worker_threads`; singleton; lock present; no `BackgroundTasks`
- [x] `future.add_done_callback` wired to submitted future (behavior test, not source grep)
- [x] `_run_files` JobStore failure → no NameError propagated
- [x] `find_entities()` LIMIT from `graph_query_limit`; floor coerced to 1
- [x] `run_pipeline()` resolves `max_relate_pairs` from config when `max_pairs=None`
- [x] `apply_transitive()` capped at `transitive_max_depth`; minimum 2 hops enforced
- [x] Cypher injection guard rejects invalid relationship names

---

*Branch: `feat/scalability-bottleneck-fixes` — GitHub PR [#1](https://github.com/Giggso-Inc/aryx/pull/1)*
