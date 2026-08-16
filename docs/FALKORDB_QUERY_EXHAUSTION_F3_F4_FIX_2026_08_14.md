# FalkorDB Query Exhaustion — F3/F4 Fix

## Context

`docker-compose.yml`'s `MAX_QUEUED_QUERIES` was raised from 25 to 250 (commit `3167f1d`) as a
stopgap after FalkorDB's query queue was observed exhausting under concurrent `/ask` traffic. A
follow-up investigation (`FalkorDB_Query_Exhaustion_Findings.xlsx`) identified five issues, F1-F5.
This pass fixes F3 and F4 only.

| ID | Issue | Severity | Status |
|---|---|---|---|
| F1 | No FalkorDB connection pooling — a fresh `FalkorDB(...)` client per adapter instance | High | Not in this PR |
| F2 | `/ask` retrieval N+1 (`gather()`'s per-hit `neighbors()`/`provenance()`) | High | Not in this PR |
| F3 | Unconditional `all_types()` full scan on nearly every `/ask` request | Medium | **Fixed here** |
| F4 | Un-batched neighbor loop in CPQ product-hint fallback | Medium | **Fixed here** |
| F5 | `MAX_QUEUED_QUERIES` bump undocumented as a stopgap | Low (informational) | Not in this PR |

## F3 — Cache and cheapen `all_types()`

`retrieve.py:all_types()` ran on nearly every `/ask` call (only the fast attribute-options path
skips it) as `sorted({e["type"] for e in reader.find_entities(limit=500)})` — a 500-row
`MATCH (e:Entity) ... LIMIT 500` scan that fetches the full `properties()` map per row just to read
off `type`.

**Fix:** two changes, both in `retrieve.py`:
1. Use `reader.distinct_types()` (already existed in `reader.py`) — a single
   `RETURN DISTINCT e.type` query with no properties payload — instead of `find_entities(limit=500)`.
2. Add a 30-second TTL cache keyed by `reader.graph_name` (a new public property on `GraphReader`
   wrapping `self._graph.name`), mirroring the existing `_subgraph_cache` pattern already in
   `reader.py`. Entity types only change on ingestion, not per question, so repeated `/ask` calls
   within the TTL window cost 0 queries instead of 1.

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

## Out of scope for this PR

- **F1** (shared FalkorDB connection pool) and **F5** (documenting the `MAX_QUEUED_QUERIES` bump
  as a stopgap) were implemented in an earlier pass but pulled back out at the requester's
  direction, to keep this PR to F3+F4 only. `src/aryx/graph/reader.py` and
  `src/aryx/graph/falkor_store.py` construct `FalkorDB(...)` directly again, as before.
- **F2** (the `/ask` retrieval N+1 in `gather()`) remains the highest-impact open item.

## Critical files

- `src/aryx/graph/reader.py` — new `graph_name` property (F3's cache key); no change to how the
  `FalkorDB` client is constructed.
- `src/aryx/graph/retrieve.py` — `all_types()` uses `distinct_types()` + TTL cache (F3).
- `src/aryx/cpq/engine.py` — product-hint fallback batches via `neighbors_batch()` (F4).
- `tests/test_graph_reader_neighbors_batch.py` — unchanged from `neighbors_batch()`'s original
  introduction (`e2b9fdc`); patches `aryx.graph.reader.FalkorDB` as before.

## Verification

1. **Unit tests**: `tests/test_falkor_isolated_marking.py`,
   `tests/test_graph_reader_neighbors_batch.py`, `tests/test_graph_isolated_scan_gate.py`,
   `tests/test_graph_query_timeout_and_export_cap.py`, `tests/test_scalability_fixes.py`,
   `tests/test_cpq_engine_catalog_scope.py`, `tests/test_cpq_history_country_mine.py`,
   `tests/test_cpq_intent_first_gate.py`, `tests/test_cpq_quantity_country_summary_fixes_2026_08_13.py`
   all passing.
2. **Regression check**: ran the full `tests/` suite; every failure observed is confirmed
   pre-existing on the unmodified `dev-rv` HEAD (config-default drift, a missing `apply_migrations`
   symbol in `file_ingest_api`, a `test_ports_seam` sys.path/module-name collision, and test-order
   pollution in `TestOrchestratePairs`). None touch F3/F4's code paths.
3. **Not yet done — recommended before merge**: live check against a running FalkorDB container
   that `all_types()` cache hits show 0 additional `MATCH (e:Entity) RETURN DISTINCT e.type` log
   lines within the 30s TTL window, and that the CPQ product-hint fallback path still resolves the
   same target attribute as before on a catalog that actually exercises the fallback branch.
