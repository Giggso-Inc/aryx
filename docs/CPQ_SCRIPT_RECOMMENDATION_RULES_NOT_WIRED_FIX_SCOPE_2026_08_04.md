# Fix Scope — Script-Backed Recommendation Rules Not Evaluated

**Date:** 2026-08-04
**Status:** Scoping only — no code changed yet.
**Triggered by:** `baselineReleaseSW_astro` resolving to "Baseline Release" instead of "Latest Release" for a non-NA/TECHEDIT order.

## Root cause (confirmed)

`src/aryx/cpq/engine.py`'s `apply_recommendation_rules()` (~line 3152) classifies recommendation actions by `set_type` but only wires **declarative** conditions to a value. `apply_constraint_rules()` already calls `BmlEvaluator.allowed_values_for_script` for constraint rules — recommendation rules have no equivalent call. A `script_recommendations_wired` counter at ~line 3219 confirms this gap is already tracked/known in the codebase, not new.

**444 script-backed recommendation rules** exist catalog-wide (per `docs/CPQ_APX_NEXT_RULE_CATALOG.md`) and are currently silently skipped, including at least one unconditional rule (`19435386407`, "Set default to Baseline Release for Baseline Release SW", added 7/25/2025) that would otherwise force `baselineReleaseSW_astro = "BASELINE RELEASE"` on every order.

## Why this is bigger than one attribute

Two declarative `LATEST RELEASE` rules for `baselineReleaseSW_astro` (region ≠ NA; `configAction_all == TECHEDIT`) DO get evaluated correctly — so the declarative path works. The gap is specific to the **script** path. Any other catalog rule that expresses its logic as a script action (not a simple field-condition) is equally silently ignored today, for any attribute, not just this one.

## Proposed scope

1. **Inventory first, no code change:** enumerate all 444 script-backed recommendation rules, group by side effect (what attribute(s) each one sets), and flag which ones are unconditional (highest risk if wired incorrectly — could clobber good values that currently pass "by accident" of not being touched).
2. **Wire evaluation:** extend `apply_recommendation_rules()` to call the same `BmlEvaluator` script path `apply_constraint_rules()` already uses, respecting existing rule-priority/ordering (script vs declarative precedence needs an explicit decision — likely: evaluate script rules in catalog `order_number` sequence, same as declarative).
3. **Regression risk check:** for every attribute touched by a newly-wired script rule, diff before/after payload on a sample of live orders across product families (Single Band, All Band, Enhanced, N70) to catch any rule that was silently inert for years and would now change previously-"working" behavior.
4. **Test coverage:** add a regression test that specifically exercises `baselineReleaseSW_astro` under: (a) US/NA normal order → confirm rule set resolves correctly once wired, (b) non-NA order → `LATEST RELEASE` via existing declarative rule (already passing), (c) TECHEDIT flow → `LATEST RELEASE`.
5. **Rollout order:** land behind a clear, isolated commit — do not bundle with the carrier-pair or hiding-rule fixes already shipped this session, since this touches a much larger rule surface (444 rules vs. 1-2 targeted attributes).

## Explicitly out of scope for this doc

- No code has been written.
- Which of the 444 script rules are safe to wire vs. need individual review is not yet determined — item 1 (inventory) must run first and may surface additional attributes with the same "correct-by-accident" pattern as `baselineReleaseSW_astro`.
