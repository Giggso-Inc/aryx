# CPQ Multi-Select Auto-Fill Over-Selection — Plan (2026-08-05)

**Status: Fix 1 + Fix 3 shipped and live-verified (2026-08-05). Fix 2 was
an interim step, superseded by Fix 3 (an explicit, HITL-confirmed product
decision) before this branch merged — see "Fix 2 (superseded)" below. A
separate, pre-existing catalog rule contradiction was discovered during
live verification — see "Known remaining issue" at the end; it is NOT
caused by, or fixable within, this change.**

## Context

Live symptom: ordering an APX NEXT XE Single Band radio, "Package Type"
was asked with zero valid options ("Please provide a value", no menu) —
an unanswerable question. Traced (not this attribute's own rules — see
below) to `auto_fill` blindly selecting 9 of 11 options on a completely
unrelated, optional multi-select attribute the customer never touched.

## Root cause

`auto_fill` (`engine.py`, ~line 5290), for a `select_type=="multi"`
attribute that is rule-governed and has an active constraint:

```python
if attr.select_type == "multi":
    if allowed_for_attr is not None:
        filled_multi[vn] = [o.item_value for o in valid_opts]
```

This treats "here is the current menu of valid choices" as "auto-select
every one of them" — for ANY constraint, however many options it leaves
standing. The function's own docstring already flags the risk for the
*no*-constraint case ("auto-picking several options with nothing to
justify the choice is the same guessing risk D2 exists to prevent") but
applies exactly that guessing to the *with*-constraint case instead,
on the unstated assumption that any constraint proves intent.

**That assumption breaks concretely**: `"Constrain Additional feature
Type"` targets `additionalSystemEnhancementFeatureType_astro` with
condition `productSelectionProduct_all <> ""` — true for essentially
every order, any product. Its 9-item `allowed_values` is a *menu
definition* ("these are the choices available for any APX Next product"),
not a recommendation to select all 9. `auto_fill` fired the moment any
product was picked and force-selected all 9, including `"ICE KIT"` — which
then triggered a separate, unrelated constraint
(`"Restrict Bulk lov for package type attribute if feature type contains
ICE KIT"`) that narrowed the real question (Package Type) to `['BULK']`,
which has zero overlap with the correct `['BULK XE', 'SINGLE XE']` —
collapsing Package Type to an unanswerable empty set.

## The actual signal that distinguishes safe from unsafe

Checked what's already auto-filled live for a real APX NEXT XE Single
Band order — 30 multi-select attrs touched, only 3 got non-empty values:

| Attribute | Options selected | Safe? |
|---|---|---|
| `provisioningAssistance_astro` | 1 of 1 total | ✅ — only one option exists at all; selecting it is unambiguous |
| `packageTypeBundles_astro` | 1 of 24 total (constrained down to exactly 1) | ✅ — constraint narrowed to a single deterministic value |
| `additionalSystemEnhancementFeatureType_astro` | 9 of 11 total | ❌ — the live bug; multiple options remain, no way to know the customer wants all of them |

The existing code **one branch above this one**, for single-select
attributes, already encodes exactly the right threshold: *"Exactly one
choice — auto-fill, no user decision needed"* (`len(valid_opts) == 1`).
Multi-select's branch never adopted the same threshold — it fires on any
non-`None` constrained set, regardless of how many options remain.

## Fix

Require `len(valid_opts) == 1` for the multi-select auto-select-via-
constraint path, exactly mirroring the single-select safeguard directly
above it. A constraint narrowing to exactly one remaining valid value is
as unambiguous for multi-select as it already is for single-select;
narrowing to several remaining values is a real, unresolved choice and
must fall through to `pending` (asked), not be guessed.

This does not touch the genuinely-justified auto-fill path for
multi-select attrs with an explicit `RecommendationRule` (a different,
already-correctly-scoped mechanism, unaffected by this change) — only the
"the constrained set IS the selection" heuristic.

## Scale

Re-ran the real Astro-APX scenario post-fix-design: of the 30 multi-select
attrs touched during a live turn, exactly **1** (`additionalSystemEnhancementFeatureType_astro`)
had more than one option auto-selected with nothing to justify it — this
is the only one this fix changes for the tested scenario. The 2 other
non-empty cases (`provisioningAssistance_astro`, `packageTypeBundles_astro`)
already satisfy `len(valid_opts) == 1` and are unaffected.

## Fix 2 (superseded) — a second finding surfaced by fixing Fix 1

Live-verifying Fix 1 alone against the real APX NEXT XE Single Band
scenario showed the fix wasn't enough: `additionalSystemEnhancementFeature
Type_astro` correctly stopped force-selecting 9 options, but it then fell
through to a **separate, pre-existing** branch (engine.py ~line 5413, "an
unconstrained multi-select with nothing to justify a subset → auto-assign
empty") which never actually checked whether a constraint was active —
only `select_type`/`required`/grid-selector membership. It silently turned
"ambiguous, still-unresolved" into "confirmed nothing selected," written
to `filled_multi` as `[]`.

`_filled_by_rule_id` treats an explicit `[]` as a real, known-empty value
(`"~".join([]) == ""`, and the attribute IS present in the map) — so any
sibling rule keyed on "does NOT contain value X" (operator `"8"`,
disjoint-from) sees that `""` and fires as if the customer had explicitly
confirmed nothing, restricting some other attribute's allowed values based
on a fact nobody actually confirmed. Live: this collapsed Package Type via
a **different** rule than Fix 1's — `"Hide Single Pack Calmshell
when...is not selected as feature type"` (condition: feature-type attr is
disjoint from `{ICE KIT}`) — fired on the false "confirmed empty," same
empty-question symptom via a different path.

**Interim fix (Fix 2, later superseded)**: the "auto-assign empty" branch
required the attribute to have no active constraint at all, so an
ambiguous constrained attribute fell through to `pending` (asked) instead.
Correct on its own terms, but live-verifying it end-to-end surfaced a new
conversational question ("Feature Type") that the product owner did not
want asked here — see Fix 3.

## Fix 3 — explicit product decision: default over ask

HITL-confirmed (2026-08-05, live conversation): asking about every
catalog-unresolved optional multi-select trades correctness for a worse
conversational experience than the product wants. Explicit decision:
prefer the XML `default_value` when it's still a currently-valid option
under any active constraint (never select a value a constraint has
already excluded); with no matching default, default to empty and do not
ask — reverting to Fix 2's simpler, unconditional "auto-assign empty"
branch, plus a default_value preference layered on top.

**This is a deliberate trade, not a correctness fix** — it knowingly
reopens the exact risk Fix 2 closed: a constrained-but-ambiguous
multi-select can again resolve to a false "confirmed empty" that a
sibling disjoint-from rule (operator `"8"`) may treat as ground truth
(`test_confirmed_empty_multiselect_can_satisfy_a_sibling_disjoint_from_
rule` documents the mechanism directly). Accepted explicitly in exchange
for fewer conversational questions; revisit if a similar empty-question
symptom resurfaces for a different attribute.

## Testing plan

1. Unit test replaying the real shape: a governed multi-select attribute
   whose constraint allows 9 of 11 options, no matching default_value —
   must NOT auto-select all 9; must default to empty (Fix 3). ✅
   `test_multiselect_with_several_constrained_options_and_no_default_
   defaults_to_empty`
2. A constrained, ambiguous multi-select whose default_value IS still
   valid — must auto-select just that default. ✅
   `test_multiselect_with_several_constrained_options_and_a_default_uses_
   the_default`
3. A default_value the constraint has excluded must never be selected
   anyway — falls back to empty. ✅
   `test_multiselect_default_value_excluded_by_constraint_falls_back_to_
   empty`
4. Regression: a governed multi-select attribute whose constraint narrows
   to exactly 1 option — must still auto-fill (unchanged from today). ✅
   `test_multiselect_constrained_to_exactly_one_option_is_still_auto_selected`
5. Regression: no active constraint at all — still defaults to empty
   (unchanged). ✅ `test_multiselect_with_no_active_constraint_stays_
   unselected`
6. Regression: a multi-select attribute with an explicit `RecommendationRule`
   setting specific values — completely unaffected (different code path,
   upstream of `auto_fill` in `evaluate_rules_loop`, unmodified by this
   change; covered by the existing recommendation-rule test files).
7. `test_confirmed_empty_multiselect_can_satisfy_a_sibling_disjoint_from_
   rule` documents Fix 3's accepted risk directly at the
   `apply_constraint_rules` level (not a regression test to keep green
   forever — a record of the known, accepted trade).
8. End-to-end live verification: replayed the real "Package Type" symptom
   against the real container (workspace 3, `Apx Next` catalog, rebuilt +
   `--force-recreate` + md5sum byte-identity check). Turn 2 now correctly
   defaults `additionalSystemEnhancementFeatureType_astro` to empty and
   proceeds without asking about it — confirming Fix 3's intended UX.
9. Full CPQ suite green (676 passed, 47 skipped — 3 pre-existing unrelated
   failures confirmed via stash-and-rerun to predate this branch entirely).
   A 4th, separately-investigated flaky failure
   (`test_cpq_rule_trace.py::TestSealing::test_record_fire_after_seal_is_
   noop`) was traced to a genuine, PRE-EXISTING bug in `rule_trace.seal()`
   (pops the session from `_open_sessions` before `record_fire` can check
   `sealed`, so a post-seal call incorrectly reopens a new session/file
   instead of no-op'ing — confirmed via `git diff --stat
   src/aryx/cpq/rule_trace.py` showing zero changes on this branch, and
   via ~1-in-3 non-deterministic reproduction rate purely from `glob()`
   file-ordering when 2+ trace files exist in the same directory).
   Unrelated to this change and out of scope for this PR — not fixed here.

## Known remaining issue (discovered during live verification, OUT OF SCOPE)

Live-replaying the full real conversation past this fix (answering
"skip" to the now-correctly-asked Feature Type question) surfaced a
**separate, pre-existing catalog rule contradiction**, unrelated to
auto_fill: for `productSelectionProduct_all = "APX NEXT XE SINGLE BAND"`,
Package Type (`packingPackageType_astro`) collapses to an empty allowed
set **regardless of the Feature Type answer**:

- Feature Type contains ICE KIT → `"Restrict Bulk lov...if feature type
  contains ICE KIT"` restricts to `['BULK']`.
- Feature Type does NOT contain ICE KIT → `"Hide Single Pack Calmshell
  when...is not selected as feature type"` restricts to `['SINGLE PACK
  CLAMSHELL']`.
- Either way, `"Constrain APX NEXT XE & XN"` (unconditional for this
  product) restricts to `['BULK XE', 'SINGLE XE']` — zero overlap with
  either of the above.

Confirmed directly via `apply_constraint_rules` with both
`filled_multi={'...': ['ICE KIT']}` and `filled_multi={'...':
['DISABLE CLOUD SERVICES']}` (i.e. any non-ICE-KIT selection) — both
produce `[]` for Package Type. This is a genuine authoring contradiction
in the source BM catalog rules for this specific product line, not an
engine bug — resolving it would mean guessing which of the three rules is
"wrong," which this codebase's D2 discipline does not do. **This fix
correctly stops masking the contradiction (the old over-selection bug
coincidentally always hit the `['BULK']` branch) and makes it visible
instead of silently guessing an answer** — the same principle behind
every other change in this doc — but does not, and cannot, resolve the
underlying catalog data issue. Needs separate follow-up (either a catalog
correction upstream, or a new declarative rule this engine has no
basis to invent on its own).
