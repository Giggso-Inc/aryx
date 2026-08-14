# FalkorDB Query Exhaustion — F1/F3/F4/F5 Fix

## Context

`docker-compose.yml`'s `MAX_QUEUED_QUERIES` was raised from 25 to 250 (commit `3167f1d`) as a
stopgap after FalkorDB's query queue was observed exhausting under concurrent `/ask` traffic. A
follow-up investigation (`FalkorDB_Query_Exhaustion_Findings.xlsx`) identified five issues, F1-F5.
This pass fixes F1, F3, F4, and F5; **F2 (the `/ask` retrieval N+1 in
`src/aryx/graph/retrieve.py:gather()`) is deliberately out of scope for this pass** and remains
open.

| ID | Issue | Severity |
|---|---|---|
| F1 | No FalkorDB connection pooling — a fresh `FalkorDB(...)` client per adapter instance | High |
| F2 | `/ask` retrieval N+1 (`gather()`'s per-hit `neighbors()`/`provenance()`) | High — **not fixed here** |
| F3 | Unconditional `all_types()` full scan on nearly every `/ask` request | Medium |
| F4 | Un-batched neighbor loop in CPQ product-hint fallback | Medium |
| F5 | `MAX_QUEUED_QUERIES` bump undocumented as a stopgap | Low (informational) |

## F1 — Shared FalkorDB client pool

`Container.graph_reader()`/`.graph_store()` (`src/aryx/ports/container.py`) construct a fresh
adapter per call by design (each binds to a workspace-scoped graph). Both adapters' `__init__`
were also each constructing a brand-new `FalkorDB(host, port)` client — and therefore a brand-new
redis-py connection pool — every time, since `FalkorDB.select_graph()` is cheap (just wraps the
client + graph name in a new `Graph` object, no I/O) but the surrounding client was not reused.

**Fix:** new module `src/aryx/graph/client_pool.py`, mirroring `src/aryx/store/pool.py`'s
`get_pool()` pattern (G12) for the graph backend — one cached `FalkorDB` client per `(host, port)`,
process-scoped, with double-checked locking:

```python
_clients: dict[tuple[str, int], FalkorDB] = {}
_lock = threading.Lock()

def get_client(host: str, port: int) -> FalkorDB:
    key = (host, port)
    if key not in _clients:
        with _lock:
            if key not in _clients:
                _clients[key] = FalkorDB(host=host, port=port)
    return _clients[key]
```

`GraphReader.__init__` (`reader.py`) and `FalkorStore.__init__` (`falkor_store.py`) now call
`get_client(...)` instead of constructing `FalkorDB(...)` directly. Every adapter instance for the
same FalkorDB host/port now shares one underlying redis-py connection pool instead of each opening
its own.

Also added a `GraphReader.graph_name` public property (`self._graph.name`) so callers outside the
class (F3's cache) can key off the graph without reaching into a private attribute.

## F3 — Cache and cheapen `all_types()`

`retrieve.py:all_types()` ran on nearly every `/ask` call (only the fast attribute-options path
skips it) as `sorted({e["type"] for e in reader.find_entities(limit=500)})` — a 500-row
`MATCH (e:Entity) ... LIMIT 500` scan that fetches the full `properties()` map per row just to read
off `type`.

**Fix:** two changes, both in `retrieve.py`:
1. Use `reader.distinct_types()` (already existed in `reader.py`) — a single
   `RETURN DISTINCT e.type` query with no properties payload — instead of `find_entities(limit=500)`.
2. Add a 30-second TTL cache keyed by `reader.graph_name`, mirroring the existing
   `_subgraph_cache` pattern already in `reader.py`. Entity types only change on ingestion, not per
   question, so repeated `/ask` calls within the TTL window cost 0 queries instead of 1.

## F4 — Batch the CPQ fallback neighbor lookups

`cpq/engine.py`'s product-hint resolution (`resolve_product_hint`'s catalog scan, ~line 2554-2580)
loops over every `BmConfigAttr` entity looking for an exact field-name match; when none exists, it
falls back to scoring every regex-matched candidate by its neighbor count, calling
`reader.neighbors(ent["id"])` once per candidate inside the loop — the same N+1 shape already fixed
in `load_product_config`'s own attribute-neighbor loop
(`docs/CPQ_LOAD_PRODUCT_CONFIG_NEIGHBORS_N_PLUS_1_PERFORMANCE_PLAN_2026_08_10.md`, commit
`e2b9fdc`) but missed in this fallback path.

**Fix:** collect fallback candidate ids in the loop without querying, then issue one
`reader.neighbors_batch(fallback_ids)` call after the loop and score from the batched result:

```python
fallback_ids: list[int] = []
for ent in attr_ents:
    ...
    if vn == "productSelectionProduct_all":
        target_id = ent["id"]
        break
    if (self._PRODUCT_FIELD_FALLBACK_RE.search(vn)
            and self._PRODUCT_FIELD_FALLBACK_HINT_RE.search(vn)):
        fallback_ids.append(ent["id"])
if target_id is None and fallback_ids:
    try:
        neighbors_by_id = reader.neighbors_batch(fallback_ids)
    except Exception:
        neighbors_by_id = {}
    target_id = max(fallback_ids, key=lambda eid: len(neighbors_by_id.get(eid, [])))
```

Behavior is unchanged: same exact-match early exit, same "most neighbors wins" tie-break among
fallback candidates, same graceful degrade-to-0 on query failure — only the number of round trips
changes (1 instead of up to `len(fallback_ids)`).

## F5 — Document the `MAX_QUEUED_QUERIES` bump as a stopgap

`docker-compose.yml`'s `falkordb` service now carries a comment stating the 25→250 bump was a
stopgap for the exhaustion this document's F1/F3 fixes address at the source, and that the value
should be reassessed once these land in production. No queue-size or timeout value was changed
(`TIMEOUT 5000` was already correct — F1/F2/F3/F4 are volume/connection issues, not
slow-query issues).

## Critical files

- `src/aryx/graph/client_pool.py` — new, shared FalkorDB client cache (F1).
- `src/aryx/graph/reader.py` — `GraphReader.__init__` uses `get_client()`; new `graph_name` property (F1).
- `src/aryx/graph/falkor_store.py` — `FalkorStore.__init__` uses `get_client()` (F1).
- `src/aryx/graph/retrieve.py` — `all_types()` uses `distinct_types()` + TTL cache (F3).
- `src/aryx/cpq/engine.py` — product-hint fallback batches via `neighbors_batch()` (F4).
- `docker-compose.yml` — stopgap comment on `MAX_QUEUED_QUERIES` (F5).
- `tests/test_graph_reader_neighbors_batch.py`, `tests/test_falkor_isolated_marking.py`,
  `tests/test_graph_isolated_scan_gate.py`, `tests/test_graph_query_timeout_and_export_cap.py`,
  `tests/test_scalability_fixes.py` — updated to patch `aryx.graph.client_pool.FalkorDB` (the new
  construction site) instead of `aryx.graph.reader.FalkorDB`/`aryx.graph.falkor_store.FalkorDB`,
  and to clear `client_pool._clients` before each test so cached clients from earlier tests don't
  leak into a test expecting its own mock.

## Verification

1. **Unit tests**: all five test files above updated and passing (68 tests across the directly
   affected files); full non-CPQ-fixture-touching modules still pass.
2. **Regression check**: ran the full `tests/` suite; every failure observed is confirmed
   pre-existing on the unmodified `dev-rv` HEAD (verified via `git stash`/`git stash pop` diffing
   before/after) — config-default drift (`graph_query_limit`, `effective_graph_backend`), a
   missing `apply_migrations` symbol in `file_ingest_api`, a `test_ports_seam` sys.path/module-name
   collision, and test-order pollution in `TestOrchestratePairs` (a real-host `redis://x` connection
   attempt that surfaces only when combined with certain other test files, present before this
   change too). None touch F1/F3/F4/F5's code paths.
3. **Not yet done — recommended before merge**: live check against a running FalkorDB container
   that `client_pool.get_client()` returns the same client across two `Container.graph_reader()`
   calls (`aryx.graph.client_pool._clients` has exactly one entry after several `/ask` requests),
   and that `all_types()` cache hits show 0 additional `MATCH (e:Entity) RETURN DISTINCT e.type`
   log lines within the 30s TTL window.
4. F2 (the `/ask` retrieval N+1 in `gather()`) remains the highest-impact open item and should be
   the next fix.
