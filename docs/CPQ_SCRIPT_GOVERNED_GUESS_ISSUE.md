# CPQ: Script-governed attr silently guesses a wrong value

## Problem Statement

`wouldYouLikeToIncludeABatterySubscription_viSoln` (SVX catalog) always resolves
to **"YES"** in the final BOM payload, regardless of the real value of the
sibling attribute its own rule depends on
(`includeASpareBatteryWithEachBodyCamera_viSoln`, confirmed "false" the entire
session). The customer never sees this attribute asked, and the payload ships
an unrequested "Yes" for a battery subscription every time.

Live-verified reproduction: fresh SVX quote → spare battery stays "false"
throughout → switch Select Model to the TAA variant → final JSON still shows
`wouldYouLikeToIncludeABatterySubscription_viSoln = "YES"`.

## Root Cause

The attribute is governed by exactly **one** recommendation rule, and it is
**script-only** (no declarative `condition_attr_id` at all):

```
if (includeASpareBatteryWithEachBodyCamera_viSoln == true) {
    return "YES";
}
return "";
```

Two compounding gaps in `auto_fill` (`src/aryx/cpq/engine.py`):

1. **`_satisfied_recommendation`** (auto_fill's own pre-check, meant to let an
   already-satisfied recommendation win before the blind first-by-order pick)
   only ever inspected the plain `condition_attr_id`/`condition_value` pair.
   It never evaluated `rule.script`/`rule.condition_script` at all, so it
   always returned `None` for this attr — even when the real sibling value
   was known and the script could have resolved correctly.

2. Because the attribute is targeted by *some* rule (`is_governed = True`),
   it reaches the **"single/boolean, 2+ options, no default: first by menu
   order — safe because a rule REQUIRES this attr to be resolved"** fallback.
   That comment's assumption is false for a script-only rule: a script can
   legitimately evaluate to "no recommendation applies" (a definitive empty
   return), not just "unknown." The fallback doesn't distinguish these
   cases — it always picks the first listed menu option ("YES", since it's
   listed before "No").

A related, separate bug was found while testing fix (1): `referenced_variables()`
(which scopes `allowed_values_for_script`'s cache key) only matched a
quoted-string comparison RHS, missing bare boolean literals (`var == true`)
entirely. Since this function's result scopes the cache key, a missed
variable meant the cache key never varied with that variable's real value —
the first-ever evaluation's result was reused for every later call regardless
of the variable's actual current state.

## Why a Straight Fix Broke APX Next

An engine-wide fix (commit `59074de`) made two changes:
- Extended `_satisfied_recommendation` to also evaluate script/condition_script
  rules (pure addition — never asks *more* questions, only resolves *more*
  attrs correctly when the script has enough information).
- Skipped the blind first-by-order fallback **entirely** whenever every rule
  governing an attr is script-only, falling through to `pending` instead.

The second change is the one with a large blast radius: APX Next's catalog
(`ApxNextConfig`) uses the exact same script-only-rule pattern pervasively
(601 recommendation rules, virtually all `condition_attr_id=0`/script-based —
"Set Base Model", "Set Validation Org...", "Default Values For Attributes
Based on Package Type...", etc.). On a genuinely fresh APX Next quote, none
of these scripts can resolve yet (they depend on other attrs not yet
answered), so **all ~30 of them** flipped from "silently guessed" to
"asked as a real question" — turning an instant, one-shot "Configuration
complete" into a 30-question flow. That flow is the *expected*, currently
correct behavior for APX Next and must not regress.

Commit `59074de` was reverted in full (`be5523b`) to restore APX Next's
working flow, which also re-reverted the SVX fix and the `referenced_variables`
cache-key fix.

## Fix (scoped, not yet applied)

Re-apply both `_satisfied_recommendation`'s script-evaluation support and the
`referenced_variables` cache-key fix unconditionally — they are strictly
additive and carry no risk to APX Next (a script that resolves is *always*
a correct answer, never a wrong guess; a correct cache key can only make
results more accurate, never worse).

**Do NOT re-apply the blind-first-by-order suppression engine-wide.** Instead,
scope it to only the specific attribute(s) confirmed to have this failure
mode, via a small, explicit allowlist (e.g. a frozenset of variable_names, or
a `(catalog_prefix, variable_name)` pair) checked immediately before the
fallback fires:

```python
_NEVER_GUESS_SCRIPT_GOVERNED: frozenset[str] = frozenset({
    "wouldYouLikeToIncludeABatterySubscription_viSoln",
})
...
if vn in _NEVER_GUESS_SCRIPT_GOVERNED and only_script_backed:
    pass  # fall through to pending, same as before
else:
    value = valid_opts[0].item_value
    ...
```

This guarantees:
- APX Next's 30 script-only-governed attrs keep their current, working
  instant-complete behavior — the allowlist check is a no-op for every
  attr not explicitly listed.
- The one confirmed-broken SVX attribute stops silently shipping "YES".
- Any *future* confirmed case (found the same way — live reproduction,
  root-caused, verified) gets added to the allowlist explicitly, rather than
  the fix silently widening its own blast radius again.

## Verification Plan

1. Re-apply `_satisfied_recommendation` script support + `referenced_variables`
   fix; add the scoped allowlist above.
2. Live-verify APX Next Enhanced still completes instantly with 0 pending
   (regression check — must match current working behavior exactly).
3. Live-verify the SVX scenario: spare battery stays "false" → switch to TAA
   → `wouldYouLikeToIncludeABatterySubscription_viSoln` stays unresolved
   (not "YES") in the final payload.
4. Full CPQ/BML test suite green.
