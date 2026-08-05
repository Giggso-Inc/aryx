# CPQ Declarative Condition Operator Handling — Plan (2026-08-05)

**Status: Phase 1 and Phase 2 both shipped (2026-08-05).** All six observed `operator1` codes (`1`,`2`,`3`,`4`,`5`,`7`,`8`) are now handled correctly; none silently fall back to `=` anymore. See the Phase 2 section and Implementation below for the `7`/`8` resolution and the `filled_multi` plumbing fix shipped alongside it.

## Context

While investigating why `customerType`/`packageInvokedFlag` show as permanently blank (`docs/CPQ_RULE_SPECIFICITY_EXECUTION_ORDER_PLAN_2026_08_04.md`'s follow-up thread), a much larger, separate defect surfaced: **`bm_config_rule_input.operator1` is never read anywhere in this codebase.** Every declarative rule condition — `HidingRule.conditions`, `ConstraintRule.conditions`, `RecommendationRule.conditions`, and the scalar `condition_attr_id`/`condition_value` pair — is evaluated as plain equality (`==`) via `evaluate_declarative_conditions`/`_condition_value_matches`, regardless of what the real BM-authored operator actually was.

**Confirmed, not hypothesized.** Cross-referencing 31 independently-authored rules whose own names contain "not"/"non-"/"unless"/"except" against their raw `operator1` values found a 31/31 match: every one uses `operator1=3` with the value being exactly the concept being negated. Example: `"Restrict Federal Bundle and Front Panel Programming For Non Federal"` → `operator1=3, value1="FEDERAL"`. Read as `<>` (not-equal), this matches the rule's own name exactly. Read as `=` (what the code actually does), the rule requires `customerType == "FEDERAL"` — which, since `customerType` is permanently unresolvable (a separate, already-documented `bmql()` gap), means the rule **never fires for anyone**, inverting its intended "applies to almost every normal customer" behavior into "never applies at all."

**Scale**: of 1766 real `bm_config_rule_input` rows in the APX Next catalog, only `operator1=4` (1316 rows, 74.5%) is handled correctly — because it happens to mean `=`, the code's implicit assumption. The remaining **450 rows (25.5%)** use `1`, `2`, `3`, `5`, `7`, or `8`, all silently collapsed into the same `=` semantic. `evaluate_declarative_conditions` is generic, catalog-agnostic code — this affects every ingested catalog (SL3500e, SVX, APX Next), not just this one.

## Confirmed operator mapping

| Code | Count (APX Next) | Meaning | Confidence | Evidence |
|---|---|---|---|---|
| 4 | 1316 (74.5%) | `=` (equals) | High (already the code's default assumption, and matches names like `"...if X is selected"`) | — |
| 3 | 317 (18.0%) | `<>` (not equal) | **Confirmed** | 31/31 independent "not/non-/unless" rule names match exactly |
| 7 | 41 (2.3%) | **Confirmed** — multi-select "current selection set INTERSECTS the expected value(s)" | **Confirmed (Phase 2)** | See Phase 2 section below |
| 8 | 69 (3.9%) | **Confirmed** — multi-select "current selection set is DISJOINT FROM the expected value(s)" | **Confirmed (Phase 2)** | See Phase 2 section below |
| 1 | 7 (0.4%) | `<` (less than) | High | `"Set TRUE if DMS Promotional Duration (Months) < than 37"` → value=`37`, op=1 |
| 2 | 4 (0.4%) | `<=` (less than or equal) | High | `"...if duration is not <=0 or >24..."` → value=`0`, op=2 |
| 5 | 12 (0.7%) | `>` (greater than) | High | `"Set TRUE if DMS Promotional Duration (Months) > than 11"` → value=`11`, op=5 |

## Phase 2 — operators 7/8 resolved (2026-08-05)

**The structural signal that cracked it**: every op7/op8 condition row's `data_type`/`value_type`/`attribute_value`/`criteria_type` fields are identical (`0`, `0`, `-1`, `0`) — no distinction there. But cross-referencing the *condition attribute itself* against `classify_select_type` (engine.py's own, already-shipped multi-select classifier — `display_type in {"6","8"}` or `attr_type=="1"` or `is_array_control_attr=="1"`) found **104 of 110 real op7/op8 rows (94.5%) target an attribute independently classified `select_type=="multi"`** (checkbox attrs: `systemEnhancementFeatureType_astro`, `additionalApplicationServices_astro`, `packageTypeBundles_astro`, `carrierSelectionMultiSelect_astro`, `secureEncryptionType_astro`). The remaining 6 rows are all `_BM_USER_GROUPS`, a BM system pseudo-attribute — still a set-membership check, just against the user's group-membership set instead of a menu attribute's current selections, not a contradiction.

**Rule-name cross-reference** (4 independently-authored rules, 0 contradictions once accounting for the standard rule-engine convention that a *validation* rule's own condition encodes the FAILURE state, not its name's positive framing — a general property of validation rules, not special-cased for these two operators):
- `"Allow Multi-Code Plug Programming only when Enhancement Level is selected"` → op8 on `ENHANCEMENT LEVEL 1` AND op8 on `ENHANCEMENT LEVEL 2` (same attr, grouped) → fires (blocks) exactly when **neither** is in the current selection. Confirms op8 = disjoint-from.
- `"Do not allow Smartlocate to be deselected when Smartvideo or SmartEvidence selected"` → op7 on `SMARTVIDEO` OR op7 on `SMARTEVIDENCE`, AND op8 on `SMARTLOCATE` → fires when (Video or Evidence currently selected) AND (Locate currently NOT selected). Confirms op7 = intersects, op8 = disjoint-from, in the same rule.
- `"Hide Smartvideo help text if Smartvideo not selected"` → op8 on `SMARTVIDEO` directly. Confirms op8.
- `"Restrict Provisioning Federal Bundle if Core Bundle is not Selected"` → op8 on `CORE BUNDLE` is the gate; op7 rows enumerate the OR-set of the rule's own restricted values. Consistent.

**A second, deeper bug found during this investigation — not just an operator question.** Even with the mapping confirmed, these conditions could not resolve, because `select_type=="multi"` attrs' current selections live in `filled_multi: dict[str, list[str]]`, a structure completely separate from the scalar `filled: dict[str, str]` dict every declarative-condition call site read from (`CpqEngine._filled_by_rule_id`). Every op7/op8 condition attribute was therefore always "missing," regardless of what was actually selected — a plumbing gap, not a mapping gap. Fixed alongside the operator mapping (see Implementation below).

## Approach

The pipeline chain that needs to carry the operator, end to end:

```
rdb.fetch_rule_inputs()          <- currently SELECTs only (rule_id, attribute_id, value1)
        │                           needs operator1 added to the SELECT and return tuple
        ▼
CpqEngine._load_rule_join_data() <- inputs_by_rule: dict[int, list[tuple[int, str]]]
        │                           needs to become list[tuple[int, str, str]] (attr_id, value, operator)
        ▼
HidingRule.conditions / ConstraintRule.conditions / RecommendationRule.conditions
        │                           dataclass field type: list[tuple[int, str]] -> list[tuple[int, str, str]]
        ▼
bml.evaluate_declarative_conditions()
        │                           core fix: branch comparison logic on the operator instead of
        │                           always doing `actual == expected`
        ▼
5 call sites in engine.py (apply_hiding_rules, apply_recommendation_rules x2,
apply_constraint_rules, resync_stale_recommendations) — unaffected if
evaluate_declarative_conditions's own signature stays stable
```

**Blast radius beyond the obvious chain** — two places in this session's own `rank_rules_by_specificity` work (`docs/CPQ_RULE_SPECIFICITY_EXECUTION_ORDER_PLAN_2026_08_04.md`) unpack `.conditions` as strict 2-tuples and will break with a 3-tuple shape:
- `CpqEngine._rule_condition_edges` (`engine.py:7393`): `for cond_id, _val in conditions`
- `CpqEngine.rank_rules_by_specificity`'s inner `_rule_rank` (`engine.py:7532`): `for cid, _v in conditions`

Both only need the attribute id, not the value or operator, for edge-building purposes — trivial to update to 3-tuple unpacking, but must not be missed.

**Comparison semantics for `evaluate_declarative_conditions`**: keep the existing OR/AND grouping (same attr_id repeated = OR, different attr_ids = AND) unchanged — that part is already correct and well-tested. Only the per-clause `hit` computation changes, from a single `==`-based check to an operator-dispatched one:
- `=` (4): existing `actual.strip().lower() in expanded` logic, unchanged.
- `<>` (3): `actual.strip().lower() not in expanded` — note this must still short-circuit AND/OR chains correctly (a `<>` clause that's already definitively true in an OR chain, or definitively false in an AND chain, behaves the same way the existing short-circuit logic already handles for `=`).
- `<`, `<=`, `>` (1, 2, 5): numeric comparison (`float(actual) < float(expected)`, etc.) — needs a safe-parse fallback (non-numeric `actual`/`expected` → unresolved, never guessed, matching this codebase's existing "never guess" convention elsewhere).
- `7`, `8` (Phase 2, shipped): `actual` is split on `"~"` into a set (a scalar with no `"~"` degrades to a one-element set, so this is a strict superset of the `=`/`<>` scalar path, not a separate code path) and checked for intersection against the expected-value set. `7` = intersects, `8` = disjoint. Implemented in `bml._operator_hit`.

## Implementation (Phase 2, shipped)

Two changes, not one:

1. **Operator mapping** — `bml._operator_hit` gained a `_MULTI_SELECT_OPERATORS = {"7", "8"}` branch: split `actual` on `"~"` into a set, intersect with the expected-value set (itself already `"~"`-expandable, unchanged from Phase 1), return the intersection result for `7` or its negation for `8`.
2. **The `filled_multi` plumbing gap** — `CpqEngine._filled_by_rule_id` now takes an optional `filled_multi: dict[str, list[str]] | None` parameter; when an attribute's variable_name is a key in `filled_multi`, its value is `"~".join(...)`-encoded into the same lookup dict `evaluate_declarative_conditions` already reads from (an explicitly-empty selection, `filled_multi[vn] == []`, still resolves to `""` — a known "nothing selected" state, not a missing one). Threaded through as a new optional `filled_multi` parameter on `apply_hiding_rules`, `apply_recommendation_rules`, `apply_constraint_rules`, `resync_stale_recommendations`, and `find_rule_inconsistencies`, wired at every call site in `evaluate_rules_loop` (the main per-turn rules pipeline) plus every other point-in-time recheck in `ask_api.py`/`bom_gate.py` that already had `session.filled_multi` in scope. All backward compatible (default `None`, existing callers unaffected).

## Critical files

- `src/aryx/cpq/rdb.py` — `fetch_rule_inputs` in both the Postgres and Oracle dialect classes (two implementations, confirmed at lines ~211 and ~611).
- `src/aryx/cpq/engine.py` — `_load_rule_join_data` (~2450-2481), the `HidingRule(...)`/`ConstraintRule(...)`/`RecommendationRule(...)` construction sites that build `.conditions` from `inputs_by_rule`, the two `rank_rules_by_specificity`-related unpacking sites, `_filled_by_rule_id` (Phase 2's `filled_multi` plumbing), and every `apply_hiding_rules`/`apply_recommendation_rules`/`apply_constraint_rules`/`resync_stale_recommendations`/`find_rule_inconsistencies` call site.
- `src/aryx/cpq/state.py` — the three dataclasses' `conditions` field type and docstrings.
- `src/aryx/cpq/bml.py` — `evaluate_declarative_conditions` and `_operator_hit`, the functions doing the comparison.
- `src/aryx/api/ask_api.py`, `src/aryx/cpq/bom_gate.py` (Phase 2) — every point-in-time `apply_*` recheck call site, updated to pass `session.filled_multi` through.

## Rollout

Shipped in two phases:
1. **Phase 1 (2026-08-05)**: operators `1`, `2`, `3`, `5` — confirmed with high confidence via independent rule-name cross-referencing. Operator `4` unchanged (already correct).
2. **Phase 2 (2026-08-05, shipped same day)**: `7`/`8` resolved (intersects / disjoint-from, multi-select membership) plus the `filled_multi` plumbing gap discovered while implementing them — see Implementation above. Both operators are wrong-by-default no longer.

No settings flag: this isn't a "which order do independently-correct things happen in" question — it's fixing declarative conditions to match what their own operator field has always said, for codes now confirmed with high confidence. The prior behavior for `1`/`2`/`3`/`5`/`7`/`8` was definitionally wrong, not a defensible alternate interpretation.

## Testing plan

1. **Unit tests for `evaluate_declarative_conditions`/`_operator_hit`** with each operator in isolation: `<>` (both hit and miss cases), `<`/`<=`/`>` (boundary values, non-numeric-value safe-fallback), `7`/`8` (both scalar-degrades-to-equals and real multi-select-set shapes), confirming AND/OR grouping and short-circuiting still work identically for mixed-operator condition lists.
2. **`_filled_by_rule_id` plumbing unit tests**: multi-select value read from `filled_multi` and `"~"`-joined; missing from both `filled`/`filled_multi` → absent; explicitly-empty `filled_multi[vn] == []` → resolves to `""`, not "missing."
3. **Replay real, confirmed catalog examples** as regression/proof tests:
   - `"Restrict Federal Bundle and Front Panel Programming For Non Federal"` shape (`customerType <> "FEDERAL"`) — fires for a non-federal customer.
   - `"Hide MCN END USER attribute for non-Federal and non-Israel customers"` shape (`customerType <> "FEDERAL" AND country <> "IL"`) — fires for a normal US customer.
   - A duration/quantity range rule (e.g. the DMS Promotional Duration `< 37` / `> 11` shapes) — gates on the numeric boundary instead of exact-match equality.
   - `"Hide Smartvideo help text if Smartvideo not selected"` shape (op8, end-to-end through `apply_hiding_rules` with `filled_multi` supplied) — fires when not selected, does not fire when selected, and (guarding the plumbing gap itself) never fires at all when `filled_multi` isn't passed through.
4. **Regression**: full CPQ/BML suite green in the container (`tests/ -k cpq`, 617 passed / 47 skipped / 3 pre-existing unrelated failures confirmed via `git stash` to fail identically before this change); `test_cpq_post_failure_guards.py`'s fake-engine lambdas updated to accept the new `filled_multi` keyword (a mock-signature drift, not a real regression). `test_cpq_rule_specificity_rank.py`/`test_cpq_payload_dependency_order.py` re-run since they depend on `.conditions` tuple shape.
5. **Live verification**: in the running container, load the real APX Next rule set, confirm the previously-dead "non-Federal" rules and the newly-fixed op7/op8 multi-select rules fire correctly for live test scenarios, and confirm nothing that previously worked (operator=4 rules) changes.

## Verification

- Audit script (already written this session) re-run post-fix to confirm operator distribution is unchanged (450 non-`4` rows still exist) but their *evaluated outcomes* now differ from pre-fix for the confirmed operators, including `7`/`8`.
- Structural cross-check re-run: 104/110 real op7/op8 rows target a `select_type=="multi"` attribute per `classify_select_type`; the remaining 6 are `_BM_USER_GROUPS`.
- Full test suite run inside the `aryx-api-1` container (bare local `pytest` is known to hang on tests invoking the real turn driver — pre-existing, unrelated to this change).
- Rebuild/redeploy, re-test the specific live scenarios already used this session (Houston/US Baseline-vs-Latest-Release case) to confirm no *new* regressions from this change specifically (that scenario's own outcome is independently gated by `customerType`'s permanent bmql-unresolvability, not by this operator fix, so it is expected to be unaffected by this change alone).
