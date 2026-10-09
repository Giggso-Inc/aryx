# `_rule_key` marked-attr target resolution (PR #503, 2026-10-09)

## Symptom

Live on workspace 1267, APX 1500 Enhanced always asked "Do You Require
Radio FCC Trigger?" regardless of Customer Type.

## Root cause

`requireForRadioFEDFCCTriggerSS_astro` is correctly governed by a
country-conditioned blank-disallow rule, so it is always asked for US.

The rule meant to hide it, `5030760` ("Hide do you required Radio FED
FCC"), could never load: it has **0** `BmConfigRuleInput` rows and **0**
`BmConfigRuleAction` rows — its only target linkage is a
`BmConfigMarkedAttr` row keyed under the rule's `source_id`
(`2296544770`), not its `entity_id` (`5030760`). `_rule_key()` only
checked `inputs`/`actions`, never `marked`, so with neither id present
there it fell back to `entity_id`, and `_resolve_targets(entity_id, ...)`
missed the real `marked_attr` row — the engine logged "no resolvable
target via action/marked_attr/chain" and dropped the rule on every pass.

Confirmed live (ws 1267, raw catalog row for rule `5030760`):
`status=1`, `0` inputs, `0` actions, `ref_id=903471941` → BmCatalog node
name `aPXNext`. The rule is **unconditional**, not "hide for non-Federal
customers" — and it is authored under the `aPXNext` node, not for APX
1500/APX 1500 Enhanced specifically.

103 other active ws 1267 type-11 rules share this exact shape (0 inputs,
0 actions, ≥1 marked attr, no script) — confirmed by query. This is a
general resolution gap, not specific to one rule.

## Why the fix alone doesn't flip the symptom

Whether rule `5030760` loads at all depends on
`cpq_empty_condition_rule_true_enabled` (plan F10) — confirmed **off**
in ws 1267's dev default. With F10 off, this fix changes nothing
observable for this symptom; it only makes the rule's target
*resolvable*, which is a precondition for F10 ever mattering here.

If F10 were turned on, whether/where the rule then applies depends on
`cpq_rule_scope_filter_enabled` and the target product's resolved
`scope_node_ids`. Confirmed live: `APX1500ENH` resolves through the
Data Table path (no BmCatalog tree node), so its `scope_node_ids` is
empty. Before the `rule_scope.py` guard added in this same PR, that
emptiness made `scope_rules_by_ancestry` a no-op — an unconditional,
`aPXNext`-scoped rule would have applied to APX 1500 Enhanced (and APX
4500/6500 Enhanced, APX 6000/8000 — every Data-Table-resolved model)
completely unfiltered, hiding the FCC question even for Federal
customers who should see it. `rule_scope.scope_rules_by_ancestry` now
excludes an unconditional (`always=True`) rule with a real `ref_id` in
exactly this "empty scope" case, closing that trap.

## What this PR does and does not do

Fixes target *resolution* (`_rule_key`/`_resolve_targets`) and the F10
scope trap above. Does **not**: turn `cpq_empty_condition_rule_true_enabled`
on, author a new per-model "Hide FCC Trigger" rule for APX 1500/APX 1500
Enhanced, or audit the other 103 similarly-shaped rules individually.
