# CPQ Multi-Select Auto-Fill Over-Selection — Plan (2026-08-05)

**Status: Fix 1 + Fix 2 shipped and live-verified (2026-08-05). A separate,
pre-existing catalog rule contradiction was discovered during live
verification — see "Known remaining issue" at the end; it is NOT caused by,
or fixable within, this change.**

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

## Fix 2 — a second finding surfaced by fixing Fix 1

Live-verifying Fix 1 alone (before Fix 2 below) against the real APX NEXT
XE Single Band scenario showed the fix wasn't enough: `additionalSystem
EnhancementFeatureType_astro` correctly stopped force-selecting 9 options,
but it then fell through to a **separate, pre-existing** branch (engine.py
~line 5413, "an unconstrained multi-select with nothing to justify a
subset → auto-assign empty") which never actually checked whether a
constraint was active — only `select_type`/`required`/grid-selector
membership. It silently turned "ambiguous, still-unresolved" into
"confirmed nothing selected," written to `filled_multi` as `[]`.

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

**Fix**: the "auto-assign empty" branch (engine.py ~line 5413) now also
requires the attribute to have **no active constraint at all**
(`attr.entity_id not in constrained_opts`), not merely "not exactly one
remaining option." An attribute a constraint narrowed to 2+ options is a
real, unresolved choice — it falls through to `pending` (asked) instead,
exactly matching this doc's own original "Fix" section above, which this
branch had silently defeated.

## Testing plan

1. Unit test replaying the real shape: a governed multi-select attribute
   whose constraint allows 9 of 11 options — must NOT auto-fill (falls to
   pending), where it previously did. ✅ `test_multiselect_with_several_
   constrained_options_is_not_auto_selected`
2. Regression: a governed multi-select attribute whose constraint narrows
   to exactly 1 option — must still auto-fill (unchanged from today). ✅
   `test_multiselect_constrained_to_exactly_one_option_is_still_auto_selected`
3. Regression: a multi-select attribute with an explicit `RecommendationRule`
   setting specific values — completely unaffected (different code path).
   Not directly re-tested here — `apply_recommendation_rules` runs in a
   separate stage of `evaluate_rules_loop`, entirely upstream of `auto_fill`;
   unmodified by this change; covered by the existing recommendation-rule
   test files.
4. End-to-end: replay the real "Package Type" symptom — confirm
   `additionalSystemEnhancementFeatureType_astro` stays unfilled (not `[]`,
   not force-selected) and Package Type's real allowed set intersection no
   longer incorporates a false "confirmed empty" fact. ✅ live-verified
   (see below) — turn 2 now correctly asks "Feature Type" with a skip
   option, instead of silently guessing.
   `test_ambiguous_multiselect_left_unresolved_does_not_falsely_satisfy_
   sibling_disjoint_from_rule` proves the mechanism at the
   `apply_constraint_rules` level directly (Case A reproduces the bug,
   Case B proves the fix).
5. Full CPQ suite green (675 passed, 47 skipped — 3 pre-existing unrelated
   failures confirmed via stash-and-rerun to predate this branch entirely);
   live re-verification against the real container (workspace 3, `Apx
   Next` catalog, APX NEXT XE Single Band scenario) — confirmed via
   rebuild + `--force-recreate` + md5sum byte-identity check.

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
