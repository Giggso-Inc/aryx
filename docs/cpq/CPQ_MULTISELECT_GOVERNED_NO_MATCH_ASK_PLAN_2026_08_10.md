# Blind-Pick (Don't Drop) a Governed Multi-Select With No Confident Match — Plan

## Context

`carrierSelectionMultiSelect_astro` is missing entirely from a real BOM payload (`/andie`
investigation, 2026-08-10) — not filled, not asked, not in `pending`. Traced with live debug
logging against the real "APX NEXT ENHANCED" configuration (workspace 39005) to `CpqEngine.
auto_fill`'s multi-select-specific branch (`engine.py:6636-6716`):

1. The attr is genuinely rule-governed — confirmed via the real attrSequence Data Table: it has a
   real coverage row for CPQModel `APXNEXTENHANCED` / base model `H55TGT9PW8BN`.
2. With 6 real carrier options and no active constraint narrowing it, `_resolve_via_data_tables`
   (which only ever fills when exactly one value is confidently correct) returns `None`.
3. That branch's own comment (`engine.py:6700`, unchanged by this plan) states the intended
   fallback: *"2+ legal values still falls through to 'ask the user' (unchanged)"*. The code does
   not actually do this — `filled_multi_now` stays `False`, nothing else happens in that `if
   attr.select_type == "multi":` block.
4. Falling out of that block, the attr reaches a SEPARATE multi-select code path
   (`engine.py:6903-7013`) built for genuinely ungoverned multi-selects. There, `rec_match` is
   falsy, `default_opt` is falsy, landing on `elif display_order is not None: pass` (§2d,
   `docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md`) — written for a truly ungoverned attribute with
   nothing to justify a value. Since this attr IS governed, that silent skip is the wrong outcome.
5. This whole thing is one long `if`/`elif` chain — once entered, none of today's earlier Group
   1/Group 2 single-select fixes (which explicitly excluded `select_type == "multi"` to avoid a
   scalar-into-list bug) ever get a chance to run for it.

**Decision (HITL, `/andie` 2026-08-10):** an initial plan proposed asking the customer instead of
guessing, on the reasoning that guessing a multi-select's real options is a bigger correctness risk
than guessing a single-select. A live scope survey of all 36 multi-select attributes in the catalog
found 17 with real menu options that would be candidates for this same gap — several with large
raw option counts (`systemEnhancementFeatureType_astro`: 222, `secureEncryptionType_astro`: 89).
Given that, the decision reversed: apply the **same tradeoff already accepted for single-select**
Data-Table-governed attrs earlier today (`_dt_governed_vns` branch, "maximizes for turn count, not
per-attribute correctness") — blind-pick the first valid option instead of asking, rather than risk
surfacing a 222-option question. This trades a small amount of per-attribute correctness for a
consistent, low-turn-count experience, matching the policy already shipped today for the analogous
single-select case.

## Approach

Two small, targeted fixes, both purely additive (no existing resolved case changes):

1. **`engine.py:6690-6709`** (the `elif allowed_for_attr is None:` sub-case inside `if attr.
   select_type == "multi":`): when `_resolve_via_data_tables` returns `None` (2+ legal values, no
   single confident match), blind-pick the first real, valid option — `filled_multi[vn] =
   [valid_opts[0].item_value]`, tagged with a distinct source (`"blind_pick_governed_multi"`, mirroring
   the single-select `"blind_pick_governed"` tag) so it stays distinguishable in `filled_source`/any
   later audit, and set `filled_multi_now = True` so the loop doesn't fall through to the second
   multi-select branch (fix 2) and re-process the same attr.
2. **`engine.py:7006-7013`** (the `elif display_order is not None: pass` case in the second,
   ungoverned-multi-select branch): narrow it to only silently skip when the attr is genuinely
   ungoverned — `elif display_order is not None and vn not in _dt_governed_vns and attr.entity_id
   not in rule_governed: pass` — with a new sibling `elif candidate_opts:` that blind-picks
   `candidate_opts[0]` the same way, for the case this plan targets (governed, layout-visible,
   nothing resolved it, reaching this second branch instead of the first). Mirrors the exact
   `rule_governed`/`_dt_governed_vns` distinction Group 1/Group 2 already established today for the
   single-select final chain — reused here, not reinvented.

Both fixes respect any active constraint already narrowing the option list (`valid_opts`/
`candidate_opts` are both already constraint-filtered before this point) and never touch a
multi-select whose value a cascade just correctly invalidated (out of scope here — no evidence this
specific gap intersects with that path; `user_answered_dropped_ids` guards remain wherever they
already apply upstream of this point).

**Explicitly not doing:** picking MORE than one option, or trying to be clever about which option
is "most likely" — first-by-catalog-order only, matching the exact convention every other blind-pick
in this file already uses.

## Critical files

- `src/aryx/cpq/engine.py` — the two additions in `auto_fill`, both purely additive.
- `tests/test_cpq_multiselect_autofill_overselection.py` or a new file — unit tests for both
  branches: a multi-select with real Data-Table governance and 2+ legal options with no confident
  match → blind-picks the first real option into `filled_multi`; a multi-select with ordinary rule
  governance (rec/con/hiding) and no default/no fired recommendation → same; a genuinely ungoverned
  multi-select with a layout loaded → unchanged silent skip (regression lock); an active constraint
  narrowing the options is still respected (blind pick comes from the narrowed set, not the full
  catalog list).

## Verification results (live, 2026-08-10)

Implementation ended up simpler than originally planned: instead of adding a NEW blind-pick branch,
the fix narrows the existing `elif display_order is not None: pass` (§2d) so the ALREADY-CORRECT,
ALREADY-TESTED `elif is_unconstrained and candidate_opts:` handler a few lines below gets a chance
to fire for a genuinely-governed-but-unconstrained multi-select — it was simply never reachable
once a layout map was loaded, which is always true in production. No new tag, no duplicated logic.

Two bugs found and fixed while implementing:
1. An initial version added a second, independent blind-pick directly inside the FIRST multi-select
   branch (`elif allowed_for_attr is None:`). This duplicated the SECOND branch's already-correct
   `is_unconstrained`-blind-pick logic with a different, untested tag
   (`blind_pick_governed_multi`) and broke an existing, passing test
   (`test_multiselect_first_available_guess_is_reopened_once_a_real_constraint_appears`) that
   depends on the specific `"default_first_available"` tag for its own re-validation contract.
   Reverted; the real gap was only in the second branch.
2. The first version of the second-branch fix excluded the `is_unconstrained and candidate_opts`
   shape unconditionally, without also requiring the attribute be genuinely governed
   (`rule_governed` or `_dt_governed_vns`) — this broke a different, deliberate, pre-existing test
   (`test_multiselect_first_available_skipped_when_layout_loaded`) that locks in "a genuinely
   UNGOVERNED multi-select stays silently skipped." Fixed by adding the same governed check Group
   1/Group 2 already established today for the single-select final chain.

Unit tests: 2 new tests in `tests/test_cpq_multiselect_autofill_overselection.py` (governed +
unconstrained + layout loaded → blind-picks via the existing handler, tagged
`"default_first_available"`; constrained-but-ambiguous + layout loaded → confirmed via `git stash`
comparison to be byte-identical to pre-fix behavior, unchanged). Full `-k cpq` regression: 871
passed (up from 869), same 3 pre-existing unrelated failures.

Live verification against the real container (workspace 39005, real "APX NEXT ENHANCED" / base
model `H55TGT9PW8BN` state): `carrierSelectionMultiSelect_astro` now resolves to a real value via
`_resolve_via_data_tables`'s own confident-match logic (source tagged `"data_table"`) instead of
silently vanishing — even better than this plan's own blind-pick fallback, since it's genuine
catalog-derived data rather than a guess. The blind-pick fallback path itself is covered by the new
unit test and remains available for configurations where no confident Data Table match exists.

## Verification

1. **Unit tests**: replay the real shape (governed multi-select, 2+ real options, no active
   constraint, no recommendation, no default, layout loaded) → `filled_multi[vn] ==
   [first_real_option]`, tagged `blind_pick_governed_multi`. A genuinely ungoverned multi-select in
   the same shape stays silently skipped (no regression to §2d's existing, deliberate behavior). An
   active constraint narrowing options to a 2+ subset is respected (first pick comes from the
   narrowed subset).
2. **Regression check**: full `-k cpq` suite — confirm the 3 known pre-existing failures are the
   only failures, and `test_cpq_multiselect_autofill_overselection.py`'s existing coverage
   (over-selection prevention) is unaffected.
3. **Live verification**: replay a real "APX NEXT ENHANCED" configuration; confirm
   `carrierSelectionMultiSelect_astro` now appears in the final payload with a real carrier value
   instead of being silently missing. Spot-check 1-2 of the other real-option-bearing multi-selects
   found in the survey (e.g. `relatedServicesType_astro`, 6 options) to confirm they now resolve
   too, and note (don't silently ignore) if any large-option-count attribute
   (`systemEnhancementFeatureType_astro`, `secureEncryptionType_astro`) reveals its own separate
   narrowing-rule gap worth a follow-up investigation.
4. Rebuild, redeploy, live-verify — same discipline as every fix today.
