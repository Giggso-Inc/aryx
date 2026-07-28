# "Change product" doesn't offer the 2 valid options — root cause + fix plan

**Status:** Root cause confirmed via direct script execution against the
running BML evaluator. No code changed — plan only, per instruction.
**Symptom (screenshot):** after "I want to change product", the engine
responds with the generic "Product has 325 available options — too many
to list here" prompt, instead of the 2 options the active Hardware
Version constraint should narrow it to (`APX NEXT ENHANCED` /
`APX NEXT XE 4G LTE PLUS 5G` — see
[docs/CPQ_PRODUCT_NOT_ASKED_ROOT_CAUSE.md](CPQ_PRODUCT_NOT_ASKED_ROOT_CAUSE.md)
for the rule itself).

## How the 325-vs-2 decision is made

`next_question_prompt` (engine.py:5808) only enumerates a numbered list
when it's handed `constrained_item_values`; otherwise it falls back to the
full, unconstrained option list, which — for `productSelectionProduct_all`
— is ~325 entries, over the enumeration threshold, producing the generic
"too many to list" message (engine.py:5841-5862). `_build_no_value_response`
supplies that constraint from `apply_constraint_rules(attrs, con_rules,
session.filled, bml_eval)`. For a script-backed rule, that call defers to
`bml_eval.allowed_values_for_script(rule.script, filled)` — so the whole
question hinges on whether that call returns the narrowed 2-value list.

## Root cause 1 (confirmed): `_TIER1_BLOCKERS` scans the whole raw script, not just the branch that matters

The actual constraint rule (`restrictAPXNextProductSelectionBasedOnHWVersionSelection`)
is a simple, fully Tier-1-parseable if/else:

```
if (hWVersion_astro == "NEXT ENHANCED LTE PLUS 5G")
    returnVal = "APX NEXT ENHANCED|^|APX NEXT XE 4G LTE PLUS 5G";
else
    returnVal = "...8 other values...";
```

But the real BM script also carries a dead `/* ... */`-commented-out block
referencing `usersessionget(...)` and `util.setConstraintValuesInSession(...)`,
plus one more live trailing statement doing the same `util.` call for an
unrelated session-variable side effect — neither of which affects
`returnVal`. `_parse_branches` (bml.py:195) runs `_TIER1_BLOCKERS.search(script)`
(bml.py:80-83, matches `util.`/`usersessionget`/etc.) against the **entire**
script text before ever looking at the if/else structure — so both
occurrences trip the blocker and the whole script is rejected as
"not Tier-1 shape", even though the part that actually determines the
allowed values is trivially resolvable. Confirmed directly:

```python
evaluate_tier1(script, {"hWVersion_astro": "NEXT ENHANCED LTE PLUS 5G"})
# -> (None, False)  — "not this shape", NOT "missing variable"
```

Compounding factor: `_strip_line_comments` (bml.py:86) only strips `//`
line comments — it does not strip `/* ... */` block comments — so the
dead commented-out `usersessionget(...)` call is not even eligible to be
ignored; it's scanned as if it were live code.

## Root cause 2 (confirmed): Tier 2 succeeds in isolation, but is a shared, capped, per-turn budget

Evaluated in isolation with a live `BmlEvaluator`, Tier 2 (the LLM
fallback) **does** correctly resolve this exact script down to the 2-value
list:

```python
BmlEvaluator(scripts={1: script}, workspace_id=21).allowed_values_for_script(
    script, {"hWVersion_astro": "NEXT ENHANCED LTE PLUS 5G"}, cache_id=1
)
# -> ['APX NEXT ENHANCED', 'APX NEXT XE 4G LTE PLUS 5G']   (stats: tier2=1)
```

So this rule is not inherently unresolvable — it's just needlessly routed
through the expensive path. That path is a **shared, per-turn-capped
resource**: `bml_tier2_max_per_turn` (config.py:325, default 50) limits
how many *distinct* scripts one `evaluate_rules_loop` pass may send to
Tier 2, combined across every rule type in that turn. The config's own
docstring notes a real large catalog has surfaced 823 distinct scripts
needing Tier 2 in a single turn before Tier-1 idiom coverage improved —
i.e., this cap is routinely under real pressure. Because
`_TIER1_BLOCKERS`'s whole-script scan pushes this rule (and likely other
rules across the catalog with the same harmless trailing `util.`/
`usersessionget` idiom) into Tier 2 unnecessarily, it competes for a
capped budget it should never have needed to draw from — and when the cap
is already spent by the time this rule's turn comes up, `allowed_values_for_script`
returns `None` ("unknown"), `apply_constraint_rules` applies no
constraint at all for `productSelectionProduct_all`, and `next_question_prompt`
falls back to the full unconstrained ~325-option list — exactly the
screenshot's symptom.

## Proposed fix (not implemented)

1. Scope `_TIER1_BLOCKERS` to the **branch bodies extracted by the if/else
   walk**, not the raw whole-script text — a dead comment or an unrelated
   trailing side-effect statement outside the matched branch should never
   block parsing the branch that actually determines `returnVal`.
2. Extend `_strip_line_comments` (or add a sibling helper) to also strip
   `/* ... */` block comments before any Tier-1 regex scan, so commented-
   out scratch code can never trip a blocker or a nested-if rejection.
3. Re-run this exact script through `evaluate_tier1` after the fix and
   confirm it now resolves via Tier 1 (0 LLM calls), freeing its slot in
   `bml_tier2_max_per_turn` for scripts that genuinely need Tier 2.

Recommend validating item 3 isn't an isolated win — grep the ingested
catalog for how many other constraint/recommendation scripts carry the
same "live if/else + dead/trailing `util.`-call" shape before treating
this as fully closed; if it's common, the same fix should meaningfully
reduce Tier-2 pressure catalog-wide, not just for this one rule.
