# FalkorDB Query Exhaustion — Findings & Fix (F2)

## Context

`docker-compose.yml`'s `MAX_QUEUED_QUERIES` was raised 25 → 250 as a stopgap
after FalkorDB's query queue exhausted under load. That bump buys headroom;
it doesn't address why the queue fills up. Investigated the actual query
volume on the `/ask` retrieval path rather than assuming the raised limit
was itself the fix.

## Root cause

No FalkorDB connection pooling, plus unbatched N+1 Cypher queries on the hot
`/ask` path. Five issues found, ranked by severity:

| # | Issue | Severity | Location |
|---|---|---|---|
| F1 | No connection pooling — `Container.graph_reader()`/`.graph_store()` construct a brand-new `FalkorDB(...)` client on every call | High | `src/aryx/ports/container.py:36-49`, `src/aryx/graph/reader.py:33-43` |
| F2 | `/ask`'s `gather()` calls `reader.neighbors(eid)`/`reader.provenance(eid)` once per matched entity instead of the existing batched `neighbors_batch()` — 50-100+ Cypher calls per request | High | `src/aryx/graph/retrieve.py:69-95` |
| F3 | `all_types()` runs an unconditional `find_entities(limit=500)` full scan on almost every `/ask` call | Medium | `src/aryx/graph/retrieve.py:23-25`, called from `src/aryx/api/ask_api.py:1054` |
| F4 | Two un-batched `neighbors()` loops in the CPQ engine: one in `load_product_config`'s attribute-value-override merge step (hot path, fires per catalog using override entities); one in `_fetch_product_option_list`'s fallback candidate scan (explicitly documented as an accepted low-frequency cost) | Medium / Low | `src/aryx/cpq/engine.py:3019`, `src/aryx/cpq/engine.py:2626` |
| F5 | The `MAX_QUEUED_QUERIES` 25→250 bump itself is a stopgap, not a fix — buys headroom without reducing query volume | Informational | `docker-compose.yml` |

Confirmed live during investigation: `gather()`'s own docstring already
states "Each graph call is recorded so the UI can show exactly what was
queried" — the recorded `tools_called` list (see below) makes the query
volume directly visible per request, not just inferred.

## This fix: F2

`gather()` collected all entity hits across up to 5 search terms, then
called `reader.neighbors(eid)` and `reader.provenance(eid)` individually for
every hit — the dominant contributor to the 50-100+ query estimate, since it
scales with (terms × hits-per-term), not a fixed cost.

Fixed by collecting every hit's entity id first, then issuing one
`reader.neighbors_batch(eids)` call for the whole request instead of one
`neighbors()` call per entity. `provenance()` has no batch form yet, so it
remains one call per entity — a smaller, separate follow-up once this half
is verified in production, same phased approach as the original CPQ N+1 fix
(`docs/CPQ_LOAD_PRODUCT_CONFIG_NEIGHBORS_N_PLUS_1_PERFORMANCE_PLAN_2026_08_10.md`).

### `tools_called` behavior change (deliberate)

`gather()`'s `calls` list is not internal-only — it's returned to the client
as `tools_called` and rendered literally in the Streamlit Ask panel's
"Graph calls (N)" expander (`src/aryx/ui/ask_panel.py`), and persisted
permanently to `ask_history_store`/`ask_thread_store` as JSONB.

Two options were weighed:
- **(A) Honest collapse** — log one `get_neighbors_batch([...])` entry
  reflecting the real, smaller number of round trips.
- **(B) Preserve appearance** — synthesize one `get_neighbors(eid)` line per
  entity for display, even though only one real query ran.

**Chose (A).** This keeps the module's own stated contract — "the UI can
show exactly what was queried" — literally true, rather than turning the
log into a display fiction. Accepted tradeoff: historical `tools_called`
rows from before this change will show the old per-entity shape; rows after
will show the new batched shape. Nothing in this codebase currently reads
`tools_called` count as a metric (checked), so this is a cosmetic, not
functional, discontinuity.

## Verification

- `tests/test_graph_gather_batching.py` (new, 5 tests): one batched
  `neighbors_batch()` call for all hits in a request; batched neighbors
  correctly mapped back to the right entity; `provenance()` still called
  per-entity; empty-hits case never calls `neighbors_batch()`; entities
  seen across multiple terms are deduplicated before batching.
- `tests/test_render_context.py`, `tests/test_graph_reader_neighbors_batch.py`,
  `tests/test_cpq_ask_route_fewshots.py` — confirmed unaffected (42 tests
  total, all passing).
- Live end-to-end trace against the real API blocked in this environment by
  an unrelated issue: the top-level `/ask` router now requires a working
  Gemini call (`model=gemini-2.5-pro`), which 404s with no valid
  `ARYX_LLM_API_KEY` configured locally. Unit coverage stands in for the
  live trace until that's available.

## Remaining work (not in this fix)

- F1 (connection pooling), F3 (`all_types()` caching), F4 (CPQ override-merge
  batching) — analyzed, not yet implemented. F1's adapters have no `close()`
  callers and no mutable state beyond the connection, so pooling is
  structurally safe; the one open question is `falkordb`/redis-py client
  behavior under genuinely concurrent request handling, which this codebase
  has never exercised before and should be smoke-tested live, not just
  reviewed statically.
- `provenance_batch()` — doesn't exist yet; needed to close the remaining
  half of F2's query count.
