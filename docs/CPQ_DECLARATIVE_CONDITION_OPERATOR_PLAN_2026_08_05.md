# CPQ Declarative Condition Operator Handling — Plan (2026-08-05)

## Context

While investigating why `customerType`/`packageInvokedFlag` show as permanently blank (`docs/CPQ_RULE_SPECIFICITY_EXECUTION_ORDER_PLAN_2026_08_04.md`'s follow-up thread), a much larger, separate defect surfaced: **`bm_config_rule_input.operator1` is never read anywhere in this codebase.** Every declarative rule condition — `HidingRule.conditions`, `ConstraintRule.conditions`, `RecommendationRule.conditions`, and the scalar `condition_attr_id`/`condition_value` pair — is evaluated as plain equality (`==`) via `evaluate_declarative_conditions`/`_condition_value_matches`, regardless of what the real BM-authored operator actually was.

**Confirmed, not hypothesized.** Cross-referencing 31 independently-authored rules whose own names contain "not"/"non-"/"unless"/"except" against their raw `operator1` values found a 31/31 match: every one uses `operator1=3` with the value being exactly the concept being negated. Example: `"Restrict Federal Bundle and Front Panel Programming For Non Federal"` → `operator1=3, value1="FEDERAL"`. Read as `<>` (not-equal), this matches the rule's own name exactly. Read as `=` (what the code actually does), the rule requires `customerType == "FEDERAL"` — which, since `customerType` is permanently unresolvable (a separate, already-documented `bmql()` gap), means the rule **never fires for anyone**, inverting its intended "applies to almost every normal customer" behavior into "never applies at all."

**Scale**: of 1766 real `bm_config_rule_input` rows in the APX Next catalog, only `operator1=4` (1316 rows, 74.5%) is handled correctly — because it happens to mean `=`, the code's implicit assumption. The remaining **450 rows (25.5%)** use `1`, `2`, `3`, `5`, `7`, or `8`, all silently collapsed into the same `=` semantic. `evaluate_declarative_conditions` is generic, catalog-agnostic code — this affects every ingested catalog (SL3500e, SVX, APX Next), not just this one.

## Confirmed operator mapping

| Code | Count (APX Next) | Meaning | Confidence | Evidence |
|---|---|---|---|---|
| 4 | 1316 (74.5%) | `=` (equals) | High (already the code's default assumption, and matches names like `"...if X is selected"`) | — |
| 3 | 317 (18.0%) | `<>` (not equal) | **Confirmed** | 31/31 independent "not/non-/unless" rule names match exactly |
| 7 | 41 (2.3%) | Membership / "is among selected" for multi-select-valued conditions | Moderate — not yet fully distinguished from 8 | `"...when Smartvideo or SmartEvidence selected"` → same attr_id repeated with each bundle value (OR-group), consistent with a multi-select contains check |
| 8 | 69 (3.9%) | A related but distinct membership/contains check | Moderate — same rule (`"Do not allow Smartlocate to be deselected..."`) uses **both** 7 and 8 for different attributes within one rule, implying a real semantic split not yet isolated | — |
| 1 | 7 (0.4%) | `<` (less than) | High | `"Set TRUE if DMS Promotional Duration (Months) < than 37"` → value=`37`, op=1 |
| 2 | 4 (0.4%) | `<=` (less than or equal) | High | `"...if duration is not <=0 or >24..."` → value=`0`, op=2 |
| 5 | 12 (0.7%) | `>` (greater than) | High | `"Set TRUE if DMS Promotional Duration (Months) > than 11"` → value=`11`, op=5 |

**Open item, not yet resolved**: operators 7 and 8 need one more investigation pass (comparing more samples, possibly checking `value_type`/`attribute_value`/`data_type` fields on the same rows for a structural distinction) before they can be fixed with the same confidence as 1/2/3/5. Recommend phasing them separately — see Rollout below.

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
- `7`, `8`: deferred until the open item above is resolved; in the meantime, fall back to today's `=` behavior for these two codes specifically (a no-regression default, not a fix) rather than guessing at an unconfirmed semantic.

## Critical files

- `src/aryx/cpq/rdb.py` — `fetch_rule_inputs` in both the Postgres and Oracle dialect classes (two implementations, confirmed at lines ~211 and ~611).
- `src/aryx/cpq/engine.py` — `_load_rule_join_data` (~2450-2481), the `HidingRule(...)`/`ConstraintRule(...)`/`RecommendationRule(...)` construction sites that build `.conditions` from `inputs_by_rule`, and the two `rank_rules_by_specificity`-related unpacking sites flagged above.
- `src/aryx/cpq/state.py` — the three dataclasses' `conditions` field type and docstrings.
- `src/aryx/cpq/bml.py` — `evaluate_declarative_conditions`, the single function actually doing the comparison.

## Rollout

Ship in two phases, not one:
1. **Phase 1 (this plan's primary scope)**: operators `1`, `2`, `3`, `5` — all confirmed with high confidence via independent rule-name cross-referencing. Operator `4` stays exactly as-is (already correct). Operators `7`/`8` explicitly fall back to today's `=` behavior (unchanged, no regression, no new guess).
2. **Phase 2 (separate, follow-up)**: resolve the `7` vs `8` distinction with further investigation, then apply the same fix pattern to them.

No settings flag: unlike the rule-specificity change, this isn't a "which order do independently-correct things happen in" question — it's fixing declarative conditions to match what their own operator field has always said, for codes already confirmed with high confidence. The current behavior for `1`/`2`/`3`/`5` is definitionally wrong, not a defensible alternate interpretation.

## Testing plan

1. **Unit tests for `evaluate_declarative_conditions`** with each operator in isolation: `<>` (both hit and miss cases), `<`/`<=`/`>` (boundary values, non-numeric-value safe-fallback), confirming AND/OR grouping and short-circuiting still work identically to today for mixed-operator condition lists.
2. **Replay real, confirmed catalog examples** as regression/proof tests:
   - `"Restrict Federal Bundle and Front Panel Programming For Non Federal"` shape (`customerType <> "FEDERAL"`) — must now correctly fire for a non-federal customer (today: never fires).
   - `"Hide MCN END USER attribute for non-Federal and non-Israel customers"` shape (`customerType <> "FEDERAL" AND country <> "IL"`) — must fire for a normal US customer.
   - A duration/quantity range rule (e.g. the DMS Promotional Duration `< 37` / `> 11` shapes) — must correctly gate on the numeric boundary instead of exact-match equality.
3. **Regression**: full CPQ/BML suite green; specifically re-run `test_cpq_rule_specificity_rank.py` (this session's own work) since it directly depends on `.conditions` tuple shape.
4. **Live verification**: in the running container, load the real APX Next rule set, confirm the previously-dead "non-Federal" rules now fire correctly for a live non-federal test scenario, and confirm nothing that previously worked (operator=4 rules) changes.

## Verification

- Audit script (already written this session) re-run post-fix to confirm operator distribution is unchanged (450 non-`4` rows still exist) but their *evaluated outcomes* now differ from pre-fix for the confirmed operators.
- Rebuild/redeploy, re-test the specific live scenarios already used this session (Houston/US Baseline-vs-Latest-Release case) to confirm no *new* regressions from this change specifically (that scenario's own outcome is independently gated by `customerType`'s permanent bmql-unresolvability, not by this operator fix, so it is expected to be unaffected by this change alone).
