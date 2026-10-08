# APX N30 / N50: "United States" is the only question (generic model scoping)

Date: 2026-10-08. Flags (all off by default): `cpq_model_resolution_tree_fallback_enabled`, `cpq_model_scoped_questions_enabled`;
uses the existing `cpq_model_resolution_enabled`, `cpq_rule_scope_filter_enabled`, `cpq_base_model_placeholder_guard_enabled`,
`cpq_derive_base_model_enabled`.

## 1. Problem

"I want to quote for APX N30" then "United States": the real CPQ sets the base model (`H15UCF9PW6AN`) and every default and
asks nothing else. Ask kept asking (`hiddenConventionalOptionsMaxQuantityAry_astro`, `LORA Region`, ...).

## 2. What the full data showed (workspace 281: full aSTRO25 XML, 3,448 attributes, 25 data tables; ws 1267 has the same shape)

| Finding | Evidence |
|---|---|
| Rules of other products fire for N30 | before: 4,732 recommendation rules loaded for the model, 904 attributes filled, base model written by rules as `M93USS9PW1AN`, then `T8838A`, then `*` (`ask.fill.attribute decided`, `tier2_satisfied_rec`) |
| The `*` comes from "Set Base Model For DMSO" | a recommendation rule on the family node (`aSTRODevices`), input `ultimateDestinationCountry` not blank, action `modelSelectionbaseModel_astro = *`. It is an ancestor of every device, so rule scoping keeps it |
| With a base model the sequence scoping never ran | `_suppress_ungoverned_attrs` returns at once when the base model is empty |
| Attributes no sequence row lists stayed visible | "silence is not a confident exclusion"; names containing `region`/`product`/`basemodel` were protected (`lORARegion_astro`, `cloudRegion_astro`, `regionalSrvMgrName_astro`, `modelSelectionBaseModelMsl_astro`) |
| The completeness check counted other families' required attributes | `find_missing_required_fields` received the whole catalog list (`isFLASHcodeAvailable_astro`, `powerAdapter_astro`, ... are `required=1` catalog-wide) |
| An optional multi-select took its first option | `systemEnhancementFeatureType_astro` = `ADAPTIVE NOISE SUPPRESSION` (`default_first_available`), then rejected by a constraint and re-asked among 227 options |

## 3. Change (no model or attribute name is in the logic)

| # | Where | What | Flag |
|---|---|---|---|
| 1 | `model_resolution.py`, `model_resolution_catalog.py` | when `Basemodeltoconfig` names no model, resolve the model from the `BmCatalog` tree: a LEAF node whose name is in the wording (longest wins). Its ancestors are the scope the existing rule scope filter keeps. With table rows nothing changes | `cpq_model_resolution_tree_fallback_enabled` (needs the existing model resolution + rule scope flags) |
| 2 | `attr_governance.py` | once the base model is known, an attribute the model's sequence rows do not list is not applicable: not asked, not filled, an earlier guess is dropped. Kept: attributes the rows list, the engine's existing exact anchors (`_DECISION_ANCHOR_VNS` + region), and attributes holding a value from the customer or the engine's own context (sources `user`/`hint`/`auto`) or a hidden attribute's own default; values only a rule or a guess put there are dropped. No attribute name or prefix | `cpq_model_scoped_questions_enabled` |
| 3 | `rules_loop.py` (`_scoped_attrs`), `ask_stale_constraint_reask.py` (`_applicable_attrs`) | the loop's returned list and the completeness check use the same scoping | same |
| 4 | `multi_fallback_unconstrained.py` | an optional multi-select nothing defaults or recommends is left empty, not given its first option | same |

The placeholder `*` is handled by the existing `cpq_base_model_placeholder_guard_enabled`; no code change.

## 4. Result (local, workspace 281, no `Basemodeltoconfig` table)

| Flags | N30 / N50 after "United States" |
|---|---|
| derive only (deployed shape) | asks `LORA Region`; 903 filled, 160 pending, base model `*` |
| + model resolution, rule scope, tree fallback, placeholder guard | base model `H15UCF9PW6AN`; 602 filled, still asks |
| + scoped questions | "Configuration complete", base model `H15UCF9PW6AN` (N30) / `H25UCF9PW6AN` (N50), 0 pending |

Other models, same data, "quote APX 900 / 4500 / 8500 for US": before 160 pending, 903 filled, base `*`; with the flags 1-2 pending
(`Feature Type`). Not a regression, but those models are not finished: see section 6.

## 5. Rollout

Enable on one workspace first (dev, ws 1267): `ARYX_CPQ_MODEL_RESOLUTION_ENABLED`, `ARYX_CPQ_RULE_SCOPE_FILTER_ENABLED`,
`ARYX_CPQ_BASE_MODEL_PLACEHOLDER_GUARD_ENABLED`, `ARYX_CPQ_MODEL_SCOPED_QUESTIONS_ENABLED` (+ the tree fallback only when the
workspace has no `Basemodeltoconfig` rows; ws 1267 has them). Then replay one quote per model (flag off vs on) and compare the
questions asked. Rollback: unset the flags.

## 6. Known limits / open items

- Models whose sequence rows are incomplete lose an attribute that the real screen shows but the rows omit: the replay is the guard.
- APX 900 / 4500 / 8500 still ask `Feature Type` (required or decision attribute for them); not changed here.
- N50 `antennasFrequency_astro` / `provAgencyType_astro` (R, no default row, not shown on the real screen): N50 completes without
  them being asked; their values are not derived here.
- The full local run needs `--timeout-worker-healthcheck` above the longest turn (a full-catalog turn is CPU bound for ~1-2 min).
- Tests run: the 15 new ones plus the 60 existing files that import the touched modules (1,105 tests): 1,086 pass, 19 fail
  identically on untouched `dev_oci` (they need the Docker-internal `oracle` host name from the machine running pytest). The
  whole repository suite was not run.

## 7. Tests

`tests/test_cpq_model_scoped_questions_2026_10_08.py` (15): tree fallback (leaf only, digit guard, table wins, flag off), scoped
attributes (anchors, system variables, answers kept; guesses not protected; flag off unchanged), the two list consumers, the
optional multi-select.

## 8. Review follow-ups (PR #475 review, N1-N4)

| # | Finding | Change |
|---|---|---|
| N1 | scoped drops used the same log reason as the old rule, so a replay could not tell them apart | `_suppress_ungoverned_attrs(..., scoped_out)` reports the attributes the new scoping dropped; the early pass logs them as `SUPPRESSED_NOT_IN_MODEL_SEQUENCE` (the old rule keeps `SUPPRESSED_UNGOVERNED`). Replay: `grep SUPPRESSED_NOT_IN_MODEL_SEQUENCE` |
| N2 | the final list scoping dropped the attribute but left a rule's / guess's value in `filled` | `rules_loop._scoped_attrs` now also pops the value from `filled`, `display_filled`, `sources` and `multi`, like the early pass. `_applicable_attrs` (completeness check) only reads the list; the loop's state it runs after is already scoped |
| N3 | the tree fallback could pick a non-model leaf whose name is in the wording | the longest name wins, and when more than one leaf still ties (the name is not unique in the tree) the model stays unresolved, so no rule is scoped out on a guess. A second catalog in the replay is still the real check |
| N4 | prerequisites of the scoped-questions flag were not listed | its description now names `cpq_model_resolution_enabled`, `cpq_rule_scope_filter_enabled`, `cpq_base_model_placeholder_guard_enabled`, `cpq_derive_base_model_enabled` (with the base model empty it changes nothing) |

Re-run locally after these changes (ws 281): APX N30 and N50 complete after "United States", 0 pending, 8 `SUPPRESSED_NOT_IN_MODEL_SEQUENCE`
records and none of the old reason; 19 tests in `test_cpq_model_scoped_questions_2026_10_08.py` pass.

| N5 | the tie rule was by name length, so two different models named together stayed unresolved, and an upgrade leaf with the same name made the fallback do nothing | `_tree_candidates` now builds `is_upgrade` from `upgrade_node_ids`, prefers a sellable (non-upgrade, non-soft-deleted) leaf, then the longest name, and leaves different models of equal length to `rank_candidates` (as on the table path). Only the SAME name on several leaves stays unresolved. 2 new tests (21 in the file) |
