# Batch `reader.neighbors()` in `load_product_config` — Performance Plan

## Context

The rule-join-data caching fix (`CPQ_RULE_JOIN_DATA_CACHING_PERFORMANCE_PLAN_2026_08_10.md`) was
correct but did not move real turn latency (still 41-57s/turn after deploying it). Re-investigated
by pulling every log line for one real turn's `run_id` and sorting the gaps between consecutive
timestamps, instead of trusting log-line *counts* (which turned out to span the container's whole
uptime, not one turn — see that plan's Correction section).

The real signal: a single 82-second turn contained **four separate ~7.3-7.6s silent gaps** — no
log output at all during them — each one immediately preceding a `CpqEngine._load_rule_join_data`
call (whether cache hit or miss), meaning the delay is not inside rule loading at all. It's in
whatever runs right before it on every one of the 4 code paths that reach rule loading in one
turn (main flow, product-switch completion, QA path, JSON-preview path).

All 4 of those paths call `CpqEngine.load_product_config(reader, workspace_id, product_hint)`
fresh, with **zero caching** — confirmed via `grep -n "load_product_config(" src/aryx/api/ask_api.py`:
4 call sites (`ask_api.py:5276, 5713, 8200, 8379`). Inside it, Step 3 (menu-item neighbor
discovery) does:

```python
for ent in attr_ents:
    eid = ent["id"]
    neighbors = reader.neighbors(eid)   # one FalkorDB round trip per attribute
    ...
```

— a classic N+1: one Cypher query per config-attribute entity, not batched, despite the
surrounding comment claiming a "two-pass approach eliminates both the cap and the N+1 pattern"
(that claim is true for the *Postgres* menu-item fetch in Step 3's second half, not for this graph
traversal in the first half).

**Confirmed live** against the real container (workspace 39005, graph `aryx_ws_39005`, 498
`ApxnextConfigdataBmConfigAttr*` entities):

```
per-entity neighbors() loop: 100 calls took 0.812s -> 8.12ms/call
per-entity neighbors() loop: 498 calls took 6.852s
```

6.85s for one `load_product_config` call, matching the observed ~7.3-7.6s gaps almost exactly (the
small remainder is `find_entities` pagination + Postgres batch-fetch, already fast). Multiplied by
4 uncached call sites in one turn: ~27-30s of the observed 40-100s turn latency is this single N+1
loop, run from scratch every time with no caching at all — unlike `_load_rule_join_data` and
`data_table_resolver._load_all_tables`, which both already have a TTL cache for exactly this
reason.

## Approach

Add a batch-neighbors primitive to `GraphReader` (`src/aryx/graph/reader.py`), one Cypher query for
however many entity ids are requested, instead of one query per id:

```python
def neighbors_batch(self, entity_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """Batched form of neighbors() -- one round trip for many entities.

    Returns {entity_id: [neighbor dicts, same shape as neighbors()]}. Entities
    with no neighbors are simply absent from the returned dict (matches
    neighbors() returning [] -- callers already use .get(eid, [])-style access).
    """
    if not entity_ids:
        return {}
    rows = self._query(
        "MATCH (e:Entity)-[r:REL]->(n:Entity) WHERE e.id IN $ids "
        "RETURN e.id AS src, n.id AS id, n.type AS type, n.name AS name, "
        "properties(n) AS attrs, r.name AS rel, 'out' AS dir "
        "UNION "
        "MATCH (e:Entity)<-[r:REL]-(n:Entity) WHERE e.id IN $ids "
        "RETURN e.id AS src, n.id AS id, n.type AS type, n.name AS name, "
        "properties(n) AS attrs, r.name AS rel, 'in' AS dir",
        {"ids": list(entity_ids)},
    )
    out: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r[0], []).append(
            {**_entity(r[1:5]), "relationship": r[5], "direction": r[6]})
    return out
```

Same UNION shape as `neighbors()`, scoped by `WHERE e.id IN $ids` instead of `{id: $id}`, with the
source id threaded through as an extra returned column so results can be grouped back per
requesting entity.

Wire it into `load_product_config`'s Step 3 with the same graceful-fallback pattern the function
already uses for `distinct_types()` two lines above (`try: ... except AttributeError: legacy
fallback`) — this keeps `OracleGraphReader` and every test double across the suite (none of which
implement `neighbors_batch`) working unchanged, just not optimized, exactly like the existing
`distinct_types` fallback:

```python
try:
    batch = reader.neighbors_batch([e["id"] for e in attr_ents])
except AttributeError:
    batch = None

for ent in attr_ents:
    eid = ent["id"]
    try:
        neighbors = batch[eid] if batch is not None else reader.neighbors(eid)
    except KeyError:
        neighbors = []
    ... (unchanged filtering logic below)
```

This is a pure read-path optimization — no change to `load_product_config`'s return shape, no
change to any rule-loading/evaluation logic, and every one of its 4 callers in `ask_api.py`
benefits automatically with zero call-site changes, same pattern as the `_load_all_tables` and
`_load_rule_join_data` fixes.

**Deliberately out of scope for this pass:** caching `load_product_config`'s result the way
`_load_rule_join_data`/`_load_all_tables` are cached. The 4 call sites already exist because
different code paths sometimes need a just-switched product's *fresh* attrs (see
`_complete_product_switch`) — a TTL cache here risks serving a stale attr list mid product-switch.
Fixing the N+1 removes ~27-30s/turn without touching that risk at all; a caching layer on top can
be a separate, smaller follow-up if the remaining cost still matters after this lands.

## Critical files

- `src/aryx/graph/reader.py` — new `neighbors_batch` method on `GraphReader`.
- `src/aryx/cpq/engine.py` — `load_product_config`'s Step 3 (~line 2216-2242) wired to use it when
  available.
- `tests/test_graph_reader_neighbors_batch.py` (new) — unit tests against a fake FalkorDB-shaped
  query layer.
- `tests/test_cpq_*` — existing `load_product_config` tests use reader fakes without
  `neighbors_batch`; the `AttributeError` fallback keeps them passing unmodified.

## Verification

1. **Unit tests**: `neighbors_batch` groups multiple entities' neighbors correctly by source id
   under one query; an entity with no neighbors is simply absent from the result dict; an empty
   `entity_ids` list short-circuits without querying.
2. **`load_product_config` tests**: existing fakes lacking `neighbors_batch` still pass via the
   `AttributeError` fallback (no changes needed); one new test with a fake `neighbors_batch`
   confirms it's preferred when present and its per-entity grouping is threaded through correctly
   into `neighbor_map`/`all_menu_ids`.
3. **Regression check**: full `-k cpq` suite, confirm the same pre-existing failures only.
4. **Live verification against the real container**: re-run the direct timing script (100/498
   calls via `reader.neighbors()` vs `reader.neighbors_batch()`) to confirm the batched form
   collapses ~6.85s down to a single-digit number of round trips; replay the same 5-turn timed
   conversation and confirm real turn latency drops meaningfully from the 41-57s baseline.
5. Rebuild, redeploy, live-verify — same discipline as every other fix today.
