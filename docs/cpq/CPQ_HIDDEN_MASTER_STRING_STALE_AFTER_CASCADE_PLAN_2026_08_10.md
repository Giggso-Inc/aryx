# Recompute the Hidden Master String After a Product/Base-Model Cascade — Plan

## Context

`carrierSelectionMultiSelect_astro` gets correctly filled (`ATT/FIRSTNET`, via today's earlier
blind-pick fix) then silently disappears from the final BOM after a mid-conversation Hardware
Version change cascades `productSelectionProduct_all` from "APX NEXT All Band" to "APX NEXT
Enhanced" (`/andie` investigation, 2026-08-10). Live-traced to `evaluate_rules_loop`
(`engine.py:4802`):

```python
if "hiddenMasterStringForAstroPortable_astro" not in filled:
    _hidden_ms = self._compute_hidden_master_string(filled, workspace_id, catalog_prefix, dt_cache, attrs=attrs)
    if _hidden_ms is not None:
        filled["hiddenMasterStringForAstroPortable_astro"] = _hidden_ms
```

`hiddenMasterStringForAstroPortable_astro` is a real, ingested attrSequence-derived value dozens of
hiding-rule scripts check membership in (`CPQ_HIDDEN_MASTER_STRING_HIDING_RULE_GAP_PLAN_2026_08_10.md`,
earlier today) — including "Hide Carrier Selection if no values available (portables)", which
governs `carrierSelectionMultiSelect_astro`. It's computed from `productSelectionProduct_all` and
`modelSelectionbaseModel_astro` (`_compute_hidden_master_string`'s own inputs), then cached directly
in `filled` and only ever recomputed when the key is **absent** — never when the inputs it was
derived from have since changed. A cascade (Hardware Version change forcing Product to re-resolve)
changes `productSelectionProduct_all` mid-conversation, but the cached master string — computed for
the OLD product — persists. The hiding rule then evaluates Carrier Selection's applicability
against the wrong product's master string, hides it, and its value gets cleared along with the
hide (`evaluate_rules_loop`'s `for k in hidden_vns: ... multi.pop(k, None)`).

`modelSelectionFrequencyBands_astro`/`modelSelectionFrequencyBandMsl_astro` are unaffected — their
own governing hiding rules check `productSelectionProduct_all` directly (no caching) or depend on a
DIFFERENT variable (`hiddenUISequenceForModelSelection_astro`) that's never computed at all and
always evaluates "unknown, stay visible." Neither goes through this specific cached value, so
neither is exposed to this bug — confirmed via a second `/andie` analysis pass, not assumed.

## Approach

Track what the cached master string was computed FOR, and recompute whenever the real inputs
change — not just when the cache key is merely absent. Minimal, additive change to the same
`evaluate_rules_loop` block:

```python
_hidden_ms_key = (
    filled.get("productSelectionProduct_all", "") + "\x1f"
    + filled.get("modelSelectionbaseModel_astro", "")
)
if (
    "hiddenMasterStringForAstroPortable_astro" not in filled
    or filled.get("_hiddenMasterStringForAstroPortable_astro_computed_for") != _hidden_ms_key
):
    _hidden_ms = self._compute_hidden_master_string(
        filled, workspace_id, catalog_prefix, dt_cache, attrs=attrs,
    )
    if _hidden_ms is not None:
        filled["hiddenMasterStringForAstroPortable_astro"] = _hidden_ms
        filled["_hiddenMasterStringForAstroPortable_astro_computed_for"] = _hidden_ms_key
```

The tracking key mirrors `_compute_hidden_master_string`'s own two real inputs (`product`,
`base_model`) exactly — no guessing at what "changed" means, just the two values the function
itself reads, joined with a `\x1f` (ASCII unit separator, never a legal character in either real
catalog value) so the pair stays a plain string. Kept as a plain string, not a tuple, deliberately:
`filled`/`session.filled` round-trips through JSON as `session_data` between turns — a tuple value
would silently become a list on deserialization, breaking the equality check on the very next turn
and defeating the fix it's part of. This marker key is underscore-prefixed, already excluded from
the customer-facing payload by `build_payload`'s existing `_is_noise_var` filter (same convention
`_bm_*`/`_configuration_id`-style internal bookkeeping keys already use), and never read by any BML
script (which only ever reads real catalog variable names).

This is purely a cache-invalidation fix: `_compute_hidden_master_string`'s own logic, every hiding
rule's evaluation, and every other caller are untouched. A conversation with no cascade (the
overwhelmingly common case) computes the value once and never recomputes it again, identical to
today. Only a conversation where Product or Base Model changes mid-way now correctly recomputes.

## Critical files

- `src/aryx/cpq/engine.py` — the cache-check block in `evaluate_rules_loop` (~line 4802).
- `tests/test_cpq_hidden_master_string.py` (existing, from earlier today's original fix) — new
  test: compute once for product A, change product to B, confirm recomputation and a hiding rule
  keyed on the new product's master string fires correctly instead of using the stale one.

## Verification results (live, 2026-08-10)

Unit tests: 2 new tests in `tests/test_cpq_hidden_master_string_cascade_staleness.py`, using the
EXACT real "Idiom D" script shape (a simplified single-if version isn't Tier-1-parseable at all,
which would have made the test pass for the wrong reason -- caught and fixed during writing). Full
`-k cpq` regression: 876 passed (up from 874), same 3 pre-existing unrelated failures.

Live verification (workspace 39005, real conversation: Product family → mid-conversation Hardware
Version change → Product cascades to "APX NEXT Enhanced") — traced with temporary instrumentation
at every `_compute_hidden_master_string` decision point:

1. Early passes correctly return "unknown" while Product/Base Model are still unresolved (expected
   multi-pass-solver behavior, not a bug).
2. Recomputes and succeeds once resolved (`APX NEXT MULTI` / `H55TGT9PW8AN` → 113 real governed
   attributes).
3. The cascade clears Product to force re-resolution; recomputation correctly returns "unknown"
   again during that gap (as it must).
4. **Recomputes again once Product resolves to `APX NEXT Enhanced`** — confirming the fix's actual
   job (recompute on change, not just on first-absence) — succeeding with the same 113-name real
   set for this base model.

**Follow-up finding, not a bug:** for this real base model (`H55TGT9PW8AN`), `carrierSelectionMulti
Select_astro` is genuinely absent from the real attrSequence coverage in both cases above --
confirmed directly against the real Data Table. This fix's job is done correctly (recompute
on cascade); the attribute's eventual hidden state for this specific base model is a correct,
data-proven outcome, not a symptom of this bug. A DIFFERENT base model (`H55TGT9PW8BN`) DOES
include it, per the earlier `/andie` investigation -- both are correct for their own base model.

## Verification

1. **Unit test**: two-pass `evaluate_rules_loop` call (mirroring
   `test_multiselect_first_available_guess_is_reopened_once_a_real_constraint_appears`'s own
   two-pass style) — pass 1 with product A computes and caches the master string; pass 2 changes
   `productSelectionProduct_all` to B — assert the cached value is recomputed (different value) and
   a hiding rule depending on it re-evaluates correctly for product B, not product A's stale
   answer. A control case (no product change between passes) asserts the value is NOT recomputed
   (same object/value, proving no regression to the original "compute once" optimization for the
   common case).
2. **Regression check**: full `-k cpq` suite — same 3 pre-existing failures only; today's earlier
   master-string tests (from `CPQ_HIDDEN_MASTER_STRING_HIDING_RULE_GAP_PLAN_2026_08_10.md`) stay
   green.
3. **Live verification**: replay the exact real conversation (product family → Hardware Version
   change forcing Product to "APX NEXT Enhanced") that surfaced this bug; confirm
   `carrierSelectionMultiSelect_astro` survives in the final payload with a real value instead of
   disappearing.
4. Rebuild, redeploy, live-verify — same discipline as every fix today.
