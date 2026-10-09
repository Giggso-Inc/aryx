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

If F10 were turned on, a naive implementation would need
`cpq_rule_scope_filter_enabled` and the target product's resolved
`scope_node_ids` to confine a node-scoped rule like `5030760` correctly.
Two live-confirmed problems with relying on that alone:

1. `APX1500ENH` resolves through the Data Table path (no BmCatalog tree
   node), so its `scope_node_ids` is empty — `scope_rules_by_ancestry`'s
   "nothing to scope by" no-op would otherwise let an unconditional,
   `aPXNext`-scoped rule apply to it (and APX 4500/6500 Enhanced, APX
   6000/8000 — every Data-Table-resolved model) completely unfiltered,
   hiding the FCC question even for Federal customers who should see it.
2. That empty-scope case is only HALF the trap: if F10 were on while
   `cpq_rule_scope_filter_enabled` is OFF entirely, `scope_rules_by_
   ancestry` is never even consulted (it short-circuits on the flag before
   looking at any rule) — the same unfiltered-everywhere outcome, for a
   different reason.

The final fix (`_load_type11_hiding_rules`) sidesteps both: it refuses,
structurally, to ever produce an `always=True` rule with a real
(non-unbound) `ref_id`, independent of either flag's value. This loader
runs once per workspace/catalog, cached and shared across every turn and
product, with no per-turn resolved-model context to check a rule's `ref_id`
against — so neither flag's state is a safe signal at load time. Only a
genuinely unbound rule (no `ref_id`, or the `"-1"` root sentinel) still
becomes `always=True`.

`rule_scope.scope_rules_by_ancestry`'s own empty-scope guard (added
earlier in this PR's review) is now unreachable for type-11 rules as a
result — kept as a second safety net for any other future caller that
sets `always=True` outside this loader (none exist today).

## What this PR does and does not do

Fixes target *resolution* (`_rule_key`/`_resolve_targets`) and refuses to
ever load a node-scoped, zero-condition rule as unconditional. Does
**not**: turn `cpq_empty_condition_rule_true_enabled` on, author a new
per-model "Hide FCC Trigger" rule for APX 1500/APX 1500 Enhanced, or audit
the other 103 similarly-shaped rules individually.

## Known limitation (deliberately accepted)

The refusal is a blanket one: it also excludes a node-scoped rule for a
model that *does* have a real catalog-tree scope, where
`scope_rules_by_ancestry` could have applied it correctly. That's an
acceptable trade-off while F10 is unused in production (confirmed off in
ws 1267's dev default) — it trades a small amount of missed correctness
for never risking the unconditional-everywhere failure mode. If F10 is
ever planned for real production use, replace this blanket refusal with a
genuine per-turn check (the rule's `ref_id` against the resolved model's
`scope_node_ids`, available at ASK time but not at this loader's load
time) instead of loosening it.
