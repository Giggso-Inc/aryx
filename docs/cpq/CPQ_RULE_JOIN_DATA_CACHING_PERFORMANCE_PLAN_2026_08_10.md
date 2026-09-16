# Cache `_load_rule_join_data` — Performance Plan

## Context

Live turns against workspace 39005 were observed taking 30-100+ seconds, first noticed while
verifying the layout-visibility baseline fix. Chasing one specific, repeatedly-logged line
("Set TRUE if feature type not equal to DELETE MISSION CRITICAL BLUETOOTH... evaluated via
BmlEvaluator at apply time") showed it fires during **rule loading**, not evaluation — at a
fixed point while iterating all ~1,300 rules. Seeing it 5+ times, ~1-1.5s apart, in one turn
meant the entire rule-loading pass was being redone 5+ times, not that one rule was slow.

The real mechanism is `CpqEngine._load_rule_join_data(workspace_id, catalog_prefix)` — the
shared fetch for `bm_config_rule_input`/`bm_config_rule_action`/marked-attr/chain join tables,
called independently by:

- `load_hiding_rules()` (~line 3276)
- `_load_value_rules()` (~line 3600) — itself called independently by
  `load_recommendation_and_constraint_rules()`, `load_recommendation_rules()`,
  `load_validation_rules()`, each paying the full cost again
- A third caller (~line 2463)

**Zero caching exists anywhere in this chain.** A single normal turn calls
`load_hiding_rules()` + `load_recommendation_and_constraint_rules()` + `load_validation_rules()`
back to back (confirmed at `ask_api.py` ~line 6221-6224) — three independent, full re-fetches of
the same join data from one block of code, in every turn. `_load_value_rules`'s own docstring
already half-acknowledges this ("repeats the same 4 join-table queries... doubles that DB work
for no reason") but the fix that produced (`load_recommendation_and_constraint_rules`) only
collapses two of the three calls, and does nothing for the 14 total call sites of these methods
across `ask_api.py`, several of which can fire within one turn (QA path, product-switch path,
JSON preview path, the main flow).

**This exact problem, in the exact same codebase, was already solved once** —
`data_table_resolver._load_all_tables` had the identical shape (confirmed live: 6+ full-table
rescans per turn, 14-27s each) and was fixed with a module-level, short-TTL cache keyed by
`(workspace_id, catalog_prefix)`. This plan applies the same proven pattern here.

## Approach

Add a module-level cache to `engine.py`, mirroring `data_table_resolver._TABLES_CACHE` exactly:

```python
_RULE_JOIN_DATA_CACHE: dict[tuple[int, str], tuple[float, tuple]] = {}
_RULE_JOIN_DATA_CACHE_TTL_SECONDS = 30.0


def _clear_rule_join_data_cache() -> None:
    """Test-isolation hook -- mirrors data_table_resolver._clear_tables_cache."""
    _RULE_JOIN_DATA_CACHE.clear()
```

Wrap `_load_rule_join_data`'s body:

```python
def _load_rule_join_data(self, workspace_id: int, catalog_prefix: str = ""):
    key = (workspace_id, catalog_prefix)
    hit = _RULE_JOIN_DATA_CACHE.get(key)
    if hit is not None:
        ts, result = hit
        if time.monotonic() - ts < _RULE_JOIN_DATA_CACHE_TTL_SECONDS:
            return result
    ... existing fetch logic unchanged ...
    result = (rdb, inputs, actions, marked, chain)
    _RULE_JOIN_DATA_CACHE[key] = (time.monotonic(), result)
    return result
```

A 30-second TTL (same as `_load_all_tables`) is short enough to stay safe against a mid-session
re-ingestion changing the underlying rule data, while covering every rule-loading call within a
single turn (turns complete well under 30s once this fix removes the redundant re-fetches, and
even today's slow turns are within that window).

This is a pure caching addition — no change to any rule-loading, parsing, or evaluation logic,
no change to any method's signature or return shape. Every one of the 3+ callers benefits
automatically with zero call-site changes, the same way the `_load_all_tables` fix required no
changes at any of ITS callers either.

## Critical files

- `src/aryx/cpq/engine.py` — new module-level cache + TTL constant + clear-cache helper, and the
  wrapping logic inside `_load_rule_join_data`.
- `tests/test_cpq_*.py` — an autouse fixture calling `_clear_rule_join_data_cache()` needs adding
  wherever tests construct fake/monkeypatched rule data for the same `(workspace_id,
  catalog_prefix)` key across multiple tests, mirroring `test_cpq_auto_fill_data_table_tier.py`'s
  existing `_clear_tables_cache` autouse fixture. Likely candidates: any test file that calls
  `load_hiding_rules`/`_load_value_rules`/`load_recommendation_and_constraint_rules` more than
  once with monkeypatched RDB data.

## Verification

1. **Unit tests**: a fresh call populates the cache; a second call within the TTL window returns
   the cached tuple without invoking the underlying fetch again (verify via a call-counting mock
   on `get_cpq_rdb`/the join-table fetch); a call with a different `(workspace_id,
   catalog_prefix)` key does NOT hit the other key's cache entry; after the TTL expires (or via
   `_clear_rule_join_data_cache()`), a fresh fetch happens again.
2. **Regression check**: re-run the full `-k cpq` suite; confirm no test relying on rule data
   changing between two calls in the same test now sees stale cached data (add
   `_clear_rule_join_data_cache()` calls wherever this surfaces).
3. **Live verification against the real container**: replay a real conversation turn, check
   `docker logs` for the number of times the "evaluated via BmlEvaluator at apply time" log line
   (or any `_load_rule_join_data`-triggered log) appears — should now be at most 1 per unique
   `(workspace_id, catalog_prefix)` per 30-second window, not once per call site. Measure real
   end-to-end turn latency before/after.
4. Rebuild, redeploy, live-verify — same discipline as every other fix today.

## Correction (post-implementation, same day)

This fix was implemented, unit-tested (5 passing tests), and confirmed working in production via
direct debug counters (`DEBUG_PERF_CALLCOUNT`): 15 cache hits / 3 misses across a 2-turn replay,
an 83% hit rate. **It is correct but was never the dominant cost.** A live 5-turn timed replay
after deploying it showed no improvement at all (41-57s/turn, same range as before).

Re-investigating the "evaluated via BmlEvaluator at apply time" log line that motivated this plan:
grouping every occurrence in the container's logs by rule name showed it is **not one rule logged
thousands of times** — it's ~30-40 distinct script-backed recommendation rules (`Default Values
for Base Model`, `Set Default Attribute Values for Packages(Pricing Admin)`, etc.), each logged
once per `_load_value_rules` call, same as designed. The original "12,100 times in one 5-turn
session" reading conflated this with the container's *entire* log history since last restart, not
one bounded session. The real cost was never rule-loading being repeated — it's a completely
different, uncached call chain. See
`docs/CPQ_LOAD_PRODUCT_CONFIG_NEIGHBORS_N_PLUS_1_PERFORMANCE_PLAN_2026_08_10.md` for the actual
dominant bottleneck (found by gap-analysis on real request timestamps, not log-line counting).
