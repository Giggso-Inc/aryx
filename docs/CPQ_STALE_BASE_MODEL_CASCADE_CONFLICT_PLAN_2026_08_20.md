# CPQ Stale Base Model on Hardware-Version Cascade — Fix Plan

**Date:** 2026-08-20
**Status:** Implemented and live-verified (branch `fix/cpq-stale-base-model-cascade-2026-08-20`)
**Severity:** High — customer-visible dead end. A correct, freshly-offered Product
value gets rejected as a "rule conflict" one turn after being chosen, and the
fallback re-ask degrades to "328 available options, type the exact name."

## Problem (live-reproduced)

Transcript (real session, APX NEXT / USA):

1. Customer configures Hardware Version = APX NEXT (4G LTE+5G), Product = APX NEXT
   Enhanced. Configuration completes normally.
2. Customer says "change hardware version to APX NEXT (4G LTE Only)".
3. System correctly detects Product depends on Hardware Version, clears it, and
   re-asks with 7 freshly-computed, genuinely valid options (APX NEXT All Band, XE
   All Band, Single Band, XE Single Band, International, XN All Band, XN Single
   Band).
4. Customer picks "APX NEXT All Band" — one of the 7 options *the system itself
   just offered as compatible with the new Hardware Version*.
5. System replies: "⚠️ Rule conflict detected. Your selections for Product and
   Hardware Version are incompatible — the catalog's own data proves these two
   values can't be combined." — then falls back to "Product has 328 available
   options — too many to list here. Please provide the exact name."

The customer picked a value the system had just told them was valid. This isn't a
values problem — the system is checking the pair against the wrong reference data.

## Root cause (verified against real code + live DB)

Two independent subsystems both decide "what Product values are valid," and they
disagree because one of them is scoped by a variable that goes stale.

1. **The re-ask that shows the 7 options** (step 3) is built by the declarative
   constraint-rule engine (`apply_constraint_rules`, `ConstraintRule` objects whose
   `condition_attr_id` points directly at Hardware Version's own entity id). This
   is correct and fresh — it has no dependency on any other attribute's value.

2. **The rejection** (step 5) comes from `CpqEngine.find_confirmed_data_table_
   conflicts` (`engine.py:7511`), which validates the pair against **raw ingested
   Data Table rows**, scoped by a *third*, hidden attribute:
   `modelSelectionbaseModel_astro` (display label "Base Model" — never shown to
   the customer under that name; confirmed live against the DB, workspace 39004:
   `hWVersion_astro`="Hardware Version" 2 options, `productSelectionProduct_all`=
   "Product" 328 options, `modelSelectionbaseModel_astro`="Base Model" 16 options).

   ```python
   # engine.py:7511-7550, find_confirmed_data_table_conflicts
   base_model = filled.get("modelSelectionbaseModel_astro", "")
   ...
   cands = _cpq_model_candidates(product, workspace_id, catalog_prefix, cache, base_model=base_model)
   for cpq_model in cands:
       for attr_a, attr_b in dt_find_inconsistent_filled_pairs_detailed(
           cpq_model, base_model, filled, workspace_id, catalog_prefix, cache,
       ):
           if both sides are customer-confirmed sources:
               flag as a confirmed conflict
   ```

   `find_inconsistent_filled_pairs_detailed` (`data_table_resolver.py:781`) scopes
   which real constraint-table rows it checks against by `(cpq_model, base_model)`
   — `base_model` here is a **lookup key**, not necessarily one of the two
   attributes named in the resulting conflict. When `base_model` is stale (left
   over from before the customer changed Hardware Version), this function
   validates the *new, correct* Hardware-Version/Product pair against the *old*
   hardware generation's rule rows — which of course don't recognize the new
   combination as valid, because they're the wrong rows entirely.

3. **Why Base Model goes stale**: the cascade-invalidation step that runs when an
   attribute changes (`_cpq_engine.find_cascade_dependents`, called from both
   `ask_api.py:2383` and `ask_api.py:3691`) walks only the **declarative rule
   graph** (hiding/recommendation/constraint rules) to decide what to clear.
   `modelSelectionbaseModel_astro` is governed by a **separate mechanism** — real
   Data Table region/base-model resolution (`engine.py:7957-7981`,
   `dt_resolve_region_allow_value`) — which the rule-graph walk has no visibility
   into. So when Hardware Version changes, `find_cascade_dependents` correctly
   flags Product as a dependent (a real constraint-rule edge exists) but never
   flags Base Model (no rule-graph edge exists, even though a real Data-Table
   dependency does) — leaving it un-cleared and stale.

4. **The re-ask degradation**: separately, `_reask_confirmed_data_table_conflict`
   (`ask_api.py:1780-1839`), the handler that builds the "Rule conflict detected"
   message and prompt, calls `next_question_prompt(attr_a)` with **no
   `constrained_item_values`** (line ~1819) — even though `next_question_prompt`
   fully supports narrowing via that exact parameter (used correctly two messages
   earlier for the 7-option Hardware-Version-driven re-ask). With nothing to
   narrow, Product's raw ~328-option catalog trips the `_MAX_ENUMERATED_OPTIONS`
   fallback ("too many to list here, provide the exact name") instead of a clean,
   narrowed re-ask.

## Fix

### Fix 1 — clear stale Base Model as part of the cascade (primary fix)

In both cascade-invalidation blocks (`ask_api.py:2398-2407` and `ask_api.py:3694-
3704`), after stripping `changed_attr` and its rule-graph dependents from
`session.filled`, also clear `modelSelectionbaseModel_astro` whenever the changed
attribute or one of its invalidated dependents is `hWVersion_astro` or
`productSelectionProduct_all`. Factored into one shared helper (`ask_api.py`, near
the other `_handle_cascade`-adjacent helpers) so both call sites stay in sync:

```python
_BASE_MODEL_VN = "modelSelectionbaseModel_astro"
_BASE_MODEL_TRIGGER_VNS = frozenset({
    "hWVersion_astro", "productSelectionProduct_all",
    "ultimateDestinationCountry", "modelSelectionRegion_astro",
})


def _invalidate_stale_base_model(
    session: "CpqSession", changed_attr: Any, dependent_eids: set[int],
    by_eid: dict[int, Any],
) -> None:
    """Base Model (modelSelectionbaseModel_astro) is Data-Table-governed, not
    rule-graph-governed -- find_cascade_dependents can never see it as a
    dependent of Hardware Version, Product, or Country/Region, so it goes
    stale and later trips a false 'confirmed conflict' in find_confirmed_
    data_table_conflicts, which uses it purely as a scoping key (not
    necessarily one of the two attrs it names) to select which real Data
    Table rows to check the CURRENT Hardware Version/Product pair against
    -- a stale key means checking against the wrong hardware generation's
    rows entirely.
    docs/CPQ_STALE_BASE_MODEL_CASCADE_CONFLICT_PLAN_2026_08_20.md.

    Safe to always clear when triggered: modelSelectionbaseModel_astro
    already has its own from-scratch re-derivation path (engine.py:7957,
    `if not filled.get(_BASE_MODEL_VN)`) that the very next rule pass runs
    unconditionally -- this only ever forces a fresh, correctly-scoped
    recompute, never leaves the attribute unset.
    """
    changed_names = {changed_attr.variable_name} | {
        by_eid[eid].variable_name for eid in dependent_eids if eid in by_eid
    }
    if changed_names & _BASE_MODEL_TRIGGER_VNS:
        session.filled.pop(_BASE_MODEL_VN, None)
        session.display_filled.pop(_BASE_MODEL_VN, None)
        session.filled_source.pop(_BASE_MODEL_VN, None)
```

Called immediately after each existing dependent-stripping loop, passing the same
`dependent_eids`/`by_eid` already in scope at both call sites.

### Fix 2 — narrow the conflict re-ask (defense in depth)

In `_reask_confirmed_data_table_conflict` (`ask_api.py:~1819`), compute a
constrained option list for `attr_a` from the real Data Table rows for the
CURRENT (post-fix-1) scope before calling `next_question_prompt`, so that even an
unanticipated future instance of this conflict class degrades to a narrowed
re-ask instead of a raw "328 options, type the exact name" dump. Lower priority
than Fix 1 — Fix 1 is expected to eliminate the false-positive conflict entirely
for this exact scenario; Fix 2 only matters if a *genuine* data-table conflict
occurs for some other reason.

## Why this direction, not an alternative

- **Rejected: teach `find_cascade_dependents` to understand Data-Table
  governance generally.** Correct long-term, but a much larger change (the
  rule-graph walker would need a second, parallel Data-Table-graph walker) for a
  bug that has exactly one concrete manifestation right now (Base Model). Scoping
  the fix to the one known stale key is smaller, safer, and directly verifiable.
- **Rejected: make `find_confirmed_data_table_conflicts` re-resolve Base Model
  itself instead of trusting `filled`.** Would duplicate the region/base-model
  resolution logic that already exists at `engine.py:7957` in a second place —
  two sources of truth for the same derivation is exactly the class of bug this
  fix is closing, not a pattern to add more of.

## Follow-up audit (2026-08-20): is this hardcoded to just Base Model?

After the initial fix landed, a natural question: is `_BASE_MODEL_TRIGGER_VNS`
a one-off patch for the exact reported transcript, or does it close the whole
class of bug? Audited every Data-Table resolver function in
`data_table_resolver.py` (`resolve_whitelist_values`, `governed_attr_names_
for_base_model`, `governed_required_attr_names_for_base_model`, `attr_ever_
governed_for_cpq_model`, `discover_cpq_models_for_base_model`, both
`find_inconsistent_filled_pairs*`) to check whether any OTHER attribute plays
the same "scoping key" role Base Model does.

**Finding 1 — Base Model is the only scoping key of its kind.** Every one of
those functions keys off `(cpq_model, base_model)` — no second, parallel
attribute plays this role anywhere in the Data-Table subsystem for this
catalog. So the fix, while it names one specific vn, actually protects every
consumer of that scoping key in the same rerun (all of the above, not just
`find_confirmed_data_table_conflicts`), since they all read the freshly-cleared
`session.filled` once the next rule pass runs.

**Finding 2 — a real second trigger the original fix missed.** Base Model's
own re-derivation (`engine.py:7958-7975`) reads two independent inputs:
Product (via `_cpq_model_candidates`) and Country/Region (via
`dt_resolve_region_allow_value`, only consulted when Product alone doesn't
already resolve it). The original `_BASE_MODEL_TRIGGER_VNS` only covered the
Product/Hardware-Version side. **A customer changing their destination
Country or Region mid-conversation hits the exact same staleness mechanism**
— `find_cascade_dependents`'s rule-graph walk has no edge from Country/Region
to Base Model either, for the identical structural reason it has none from
Hardware Version. Widened `_BASE_MODEL_TRIGGER_VNS` to include
`ultimateDestinationCountry` and `modelSelectionRegion_astro` to close this.

**Not found**: any evidence of a third, undiscovered scoping-key attribute
beyond Base Model, or any other consistency-check mechanism structurally
similar to `find_confirmed_data_table_conflicts` that this fix doesn't already
cover.

## Risk assessment

- **Blast radius**: touches the two cascade-invalidation blocks, which run on
  every change-request (not just Hardware-Version-driven ones). The added clear
  is a no-op unless the changed/dependent set intersects `hWVersion_astro`,
  `productSelectionProduct_all`, `ultimateDestinationCountry`, or
  `modelSelectionRegion_astro` — every other change-request attribute is
  unaffected.
- **Needs verification**: confirm Base Model correctly re-derives (doesn't come
  back empty, or resolve to a value inconsistent with the NEW Product) when
  cleared via a Product-initiated change (not just a Hardware-Version-initiated
  one) — both trigger vns are included in `_BASE_MODEL_TRIGGER_VNS` specifically
  to cover this.
- **What could still go wrong**: if Base Model's own re-derivation
  (`engine.py:7957`) requires a country/region value that isn't set yet at the
  point this cascade runs, it may leave Base Model unset rather than freshly
  resolved — acceptable (unset is never worse than stale-and-wrong) but worth
  confirming doesn't regress into a new "always ask" loop for Base Model itself
  (it's never a chat-visible question in this catalog, so it should silently
  resolve on the next full rule pass regardless).

## Verification plan

1. Unit test: two-attribute cascade fixture (Hardware Version → Product,
   synthetic vns standing in for `hWVersion_astro`/`productSelectionProduct_all`)
   proving `modelSelectionbaseModel_astro` is cleared from `session.filled` after
   a Hardware-Version change, for both the single-change (`ask_api.py:2383`) and
   multi-change (`ask_api.py:3691`) cascade paths.
2. Unit test: an unrelated attribute change (not Hardware Version or Product)
   leaves `modelSelectionbaseModel_astro` untouched — confirms the fix is scoped,
   not a blanket clear on every cascade.
3. Live replay: rebuild + redeploy `api`, replay the exact transcript from this
   doc's Problem section (APX NEXT → USA → change Hardware Version to 4G LTE
   Only → pick APX NEXT All Band) and confirm no "Rule conflict detected" fires,
   configuration completes normally.
4. Full CPQ regression suite — confirm no new failures against the established
   baseline (per this session's `docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_
   19.md`-style worktree comparison discipline if any ambiguous failure surfaces).

## Implementation summary (2026-08-20)

- Added `_invalidate_stale_base_model` (`ask_api.py`, just above `_handle_cascade`)
  and wired it into both cascade call sites (`ask_api.py:2383` single-change,
  `ask_api.py:3691` multi-change), right after each site's existing
  dependent-stripping loop.
- New `tests/test_cpq_stale_base_model_cascade_2026_08_20.py` (8 tests, all
  passing): confirms Base Model clears when the changed attribute or a cascade
  dependent is Hardware Version, Product, Destination Country, or Region;
  stays untouched for unrelated changes; and is a no-op when Base Model was
  never filled.
- Full CPQ-focused regression run (`pytest tests/ -k cpq`, 1269 passed, 47
  skipped, 13 failed) — all 13 failures are byte-identical to the pre-existing
  baseline already confirmed in this session's earlier worktree comparison
  (`docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md`) — zero new failures.
- Live-verified against the real APX Next catalog (workspace 39004, rebuilt +
  redeployed `api` container): replayed the exact transcript from this doc's
  Problem section (configure for USA → Hardware Version 4G LTE+5G → Product APX
  NEXT Enhanced → change Hardware Version to 4G LTE Only → pick APX NEXT All
  Band). **No "Rule conflict detected" message fired** — the flow proceeded
  cleanly to the next real pending question (Base Model, then Feature Type),
  confirming the false-positive conflict this doc targets is gone.
- Fix 2 (narrowing `_reask_confirmed_data_table_conflict`'s fallback) was not
  needed to resolve the reproduced scenario — deferred as a lower-priority
  defense-in-depth item, not implemented in this pass.

## PR #235 review feedback (2026-08-20) — addressed

**Medium**: the original test suite only exercised `_invalidate_stale_base_
model` as a pure function against a hand-built session — nothing proved Base
Model actually gets recomputed correctly by the real rule-evaluation
pipeline afterward, as opposed to being left absent indefinitely. Added
`test_base_model_is_never_stale_across_a_real_two_turn_cascade` (same test
file), which drives the real `CpqEngine.evaluate_rules_loop`/`auto_fill`
pipeline (mocking only `data_table_resolver._load_all_tables` with a
synthetic-but-realistic 5-tuple fixture) across two turns: Hardware Version
changes, then Product is answered. This surfaced a genuine correction to the
fix's own docstring: Base Model does **not** resolve within the same turn as
the Hardware-Version-change trigger — its own derivation reads Product,
which was invalidated by the same cascade, so it correctly stays unresolved
until Product is answered (confirmed via a standalone debug run printing
`session.filled` after each stage). The docstring previously claimed the
next rule pass "runs unconditionally" in a way that implied same-turn
resolution; corrected to state the real, weaker, but sufficient guarantee:
Base Model is never left holding its stale pre-trigger value, even if
resolving it takes an additional turn.

**Low**: added a one-line comment on `_invalidate_stale_base_model`
explaining the identity-based (not value-changed) trigger is deliberate —
re-derivation is cheap/idempotent (a few Data Table row scans, no LLM call),
so a rare redundant recompute on a no-op "change" is the safe side to err on
versus risking a missed real one.
