# Prefetch Tier-2 Before `auto_fill`, Not Just After — Plan

## Context

After shipping `GraphReader.neighbors_batch` (docs/CPQ_LOAD_PRODUCT_CONFIG_NEIGHBORS_N_PLUS_1_
PERFORMANCE_PLAN_2026_08_10.md), a live 5-turn timed replay showed a real but partial improvement
(~51s/turn average down to ~47s) — turns are still 32-52s. Re-ran the gap-analysis technique from
that plan (sort log-line timestamp deltas for one real `run_id`, don't trust log-line counts) on
the post-fix trace.

The dominant remaining cost: `evaluate_rules_loop`'s own `cpq_perf: auto_fill took Xs pass=0` log
line showed **20.6s and 21.5s** for two separate turns' first pass — bigger than everything else
in the trace combined. The timer wraps nothing but the `self.auto_fill(...)` call itself
(`engine.py:4822-4834`), so this cost is genuinely inside `auto_fill`, not mislabeled.

`auto_fill` has an internal helper, `_satisfied_recommendation` (~line 5870), that checks — for
every still-unfilled attribute being considered for auto-fill — whether any recommendation rule
targeting it already fires against the current `filled` state, via the same Tier-1/Tier-2 script
machinery `apply_recommendation_rules` uses (`bml_eval.allowed_values_for_script`/
`condition_holds`, ~lines 5906/5913). This runs once per (unfilled attr, targeting rule) pair,
serially, no different from the "one script at a time" pattern the existing `prefetch_tier2`
mechanism (Amendment 18, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md) was built to eliminate for
hiding rules and for `apply_recommendation_rules`/`apply_constraint_rules`.

**The actual gap:** `evaluate_rules_loop` already prefetches Tier-2 for `rec_rules`/`con_rules`
scripts — but at `engine.py:4862-4864`, which runs *after* `auto_fill`, specifically to warm the
cache for the `apply_recommendation_rules`/`apply_constraint_rules` calls that come later in the
same pass. `auto_fill`'s own internal use of the exact same `rec_rules` scripts, a few lines
*earlier*, has no prefetch covering it at all. On pass 0 — when the most attributes are unfilled,
so `_satisfied_recommendation` has the most (attr, rule) pairs to check — this uncovered gap is
paid in full, serially, over the network.

This is not a new mechanism to build — `prefetch_tier2` already exists, is already proven safe
(dedupes by (script, variables) key, thread-pooled, `max_workers=min(16, len(pending))`), and
already has the exact request-builder needed (`_bml_prefetch_requests(attrs=..., rec=...,
filled=...)`). The fix is purely about calling it one more time, earlier, against the pre-
`auto_fill` `filled` state.

## Approach

Add one more `bml_eval.prefetch_tier2(...)` call in `evaluate_rules_loop` (`engine.py`), right
before the `auto_fill` call, using the `filled` state as it stands at that point (before
`auto_fill` can change it):

```python
if bml_eval is not None:
    bml_eval.prefetch_tier2(self._bml_prefetch_requests(
        attrs=attrs, rec=rec_rules, filled=filled))

_t0 = time.monotonic()
filled, display_filled, _ = self.auto_fill(...)
```

`con_rules` is deliberately excluded from this new call — `auto_fill`'s own `_satisfied_
recommendation` helper only ever consults `rec_rules` (constraint rules narrow allowed *options*,
they don't drive `_satisfied_recommendation`'s auto-fill decision), so including `con` here would
just prefetch scripts nothing here will read this pass.

Calling `prefetch_tier2` twice per pass (once before `auto_fill`, once after, per the existing
line 4862-4864) is safe and non-wasteful by design: `_prepare`'s cache key already includes the
current variable snapshot the script reads, so a script whose referenced variables happened not
to change between the two calls is simply a cache hit the second time — `prefetch_tier2`'s own
docstring already documents this as the intended, harmless behavior for exactly this kind of
overlapping coverage.

This is a pure latency change — no change to `auto_fill`'s, `apply_recommendation_rules`', or
`_satisfied_recommendation`'s logic, no change to any return shape or call signature. Every caller
of `evaluate_rules_loop` benefits automatically.

## Critical files

- `src/aryx/cpq/engine.py` — one new `prefetch_tier2` call in `evaluate_rules_loop`, immediately
  before the existing `auto_fill` call (~line 4821).
- `tests/test_cpq_auto_fill_tier2_prefetch_gap.py` (new) — unit test proving the new prefetch call
  fires with the pre-`auto_fill` `filled` state, before `auto_fill` runs.

## Verification

1. **Unit test**: a fake `bml_eval` records the order and argument snapshot of every
   `prefetch_tier2` call relative to `auto_fill`'s own script-evaluation calls; assert the new
   prefetch call happens first, with a `filled` snapshot equal to the pre-`auto_fill` state.
2. **Regression check**: full `-k cpq` suite, same pre-existing failures only.
3. **Live verification against the real container**: replay the same 5-turn timed conversation;
   confirm `cpq_perf: auto_fill took Xs pass=0` drops from the observed ~20-21s baseline, and that
   overall turn latency drops further than the `neighbors_batch` fix alone achieved.
4. Rebuild, redeploy, live-verify — same discipline as every other fix today.
