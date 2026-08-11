# Tier-2 Cache Key Hashes the Entire `filled` State — Finding (Not Yet Fixed)

## Status

**Investigated and root-caused, deliberately NOT fixed this session** — the correctness risk and
blast radius warrant a dedicated, separate effort with its own plan and sign-off, not a rushed
addition on top of today's two shipped latency fixes (`CPQ_LOAD_PRODUCT_CONFIG_NEIGHBORS_N_PLUS_1_
PERFORMANCE_PLAN_2026_08_10.md`, `CPQ_AUTO_FILL_TIER2_PREFETCH_GAP_PLAN_2026_08_10.md`). Those two
fixes are real and shipped (avg. turn latency on a 5-turn replay: ~51s → ~43s). This doc exists so
the next investigation doesn't have to re-derive what's below from scratch.

## The finding

After shipping both fixes above, `cpq_perf: auto_fill took Xs pass=0` was still ~19-21s on the
first pass of a fresh product/model selection — bigger than every other logged cost combined.
Added temporary per-attribute timing inside `auto_fill`'s main attribute loop
(`engine.py:6091`-ish) and found the cost wasn't concentrated in a few slow attributes — it was
spread broadly across nearly all ~380 attributes, each paying roughly 50ms-800ms.

Traced this to `BmlEvaluator._prepare` (`src/aryx/cpq/bml.py:1357`):

```python
key = (kind, self._workspace_id, self._catalog_prefix,
       cache_id if cache_id is not None else hash(script),
       frozenset(variables.items()))
```

`variables` here is the **entire `filled` dict** passed by the caller — not the subset of
variables the script actually reads. The cross-process durable cache
(`_durable_key`, `bml.py:1413`) uses the identical full-state identity for the same documented
reason: "full variable state... carries no new correctness risk beyond the in-memory cache's own
already-established semantics."

This means:
- Any two calls with a `filled` dict differing by even one unrelated key produce a different cache
  key — even if the script in question never reads that key.
- `auto_fill`'s own loop does `filled[vn] = value` progressively as it iterates (confirmed:
  `engine.py` lines inside the loop write directly into the same `filled` dict the loop is
  iterating with). So attribute #50's cache key already differs from attribute #1's, which differs
  from the prefetch snapshot taken before the loop started — meaning only the very first attribute
  processed can ever be a guaranteed cache hit from a single up-front prefetch.
- The durable, cross-session cache suffers the same problem across turns: a real conversation
  naturally accumulates more filled attributes turn over turn, so the exact global state essentially
  never repeats, and the "durable" cache rarely pays off for exactly the turns where it would help
  most (later turns, richer state).

## Why this wasn't fixed today

The full-state key is not an oversight — the existing docstring explains the reasoning: Tier-2 is
the *fallback* for scripts too complex for Tier-1's structural regex-idiom parser to resolve. For
those scripts we generally have no reliable way to know which variables they actually depend on
without evaluating them — which is exactly why they're on Tier-2 in the first place. Narrowing the
key incorrectly (excluding a variable a script secretly depends on) risks returning a **stale,
wrong recommendation or hiding decision to a real customer** — a correctness regression, not just
a slow turn. This is a materially different risk class than the two fixes shipped today (pure
latency, zero behavior change, narrow blast radius).

## Where a real fix might start (unexplored, for the next attempt)

- Tier-1 idioms (`evaluate_tier1`/`evaluate_hide_tier1`/the regex-idiom matchers in `bml.py`
  already extract specific variable names via named regex groups (e.g. `m.group("master")`,
  `m.group("basemodel")`) when they DO match. For the subset of scripts Tier-1 successfully
  parses, the specific referenced variable names are already known — a scoped cache key limited to
  just those names would be provably safe for that subset, with zero risk to the genuinely-opaque
  Tier-2/LLM-only scripts, which would keep today's conservative full-state key unchanged.
- Any such change needs its own audit of every Tier-2 call site (`hide_for_script`,
  `condition_holds`, `allowed_values_for_script`, `prefetch_tier2`, both the in-memory
  `_SHARED_SCRIPT_CACHE` and the durable Postgres-backed cache) plus a live audit of how often
  real scripts in the ingested catalog fall into "Tier-1 parseable" vs. genuinely opaque, before
  estimating real-world impact.
