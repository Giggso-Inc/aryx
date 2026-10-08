# N50 on dev: a trademark mark in the display name hid the real model from the not-applicable guard

Date: 2026-10-08. Behind the existing `cpq_model_scoped_questions_enabled` (off by default); only matters where
`cpq_basemodel_display_name_resolution_enabled` is on (dev has it on).

## 1. Problem (dev, ws 1267)

"i want to quote APX N30 for US" completes; "i want to quote APX N50 for US" does not: "This configuration is missing required
data: Is FLASHcode Available?, Quantity, Power Adapter".

## 2. What the dev logs and table showed

| Evidence | Finding |
|---|---|
| `ask.model.resolved` | `APXN50`, node `aPXN50`, 3 base models: model resolution is right |
| fill log | `modelSelectionFrequencyBands_astro` ends at `TIER0_NOT_APPLICABLE_GUARD`, value unset, in every pass; the base model stays unset (`REGION_AND_BASE_MODEL`); `SCOPED drops 0` |
| `ask.guard.device_resolved` | `models: ["APXN50FLASHPORT"]`, `model_count: 1` (the real model is missing) |
| `ws1267_basemodeltoconfig` | the real model's `displayModel` is `APX(TM) N50` (U+2122), its flashport rows are plain `APX N50` |

## 3. Cause

`resolve_cpq_model_from_display_name` (used first by `resolve_product_cpq_models_from_hint` when
`cpq_basemodel_display_name_resolution_enabled` is on) looks for the display name inside the customer's wording, collapsing
whitespace only. `APX(TM) N50` is not inside "...APX N50...", so only the flashport rows matched. The guard asks "does any
resolved model ever list this attribute?": it looked at the flashport model alone, found no frequency band in its rows, called the
band "not applicable" and cleared it. Without the band the 3 base models cannot be narrowed, so no base model is derived, the
sequence scoping of #475 / #480 has nothing to work with, and the catalog-wide required flags (FLASHcode, power adapter, ...) are
counted as missing.

Reproduced locally (ws 281, the same table loaded, the display-name flag on, dev's other flags): guard models
`["APXN50FLASHPORT"]` (and `["APXN30FLASHPORT"]`), N50 ends with no band, no base model and the Flashcode questions. Without that
flag (my earlier local runs) the other lookup path was used and N50 passed, which is why it was not seen before.

## 4. Change

`data_table/data_table_product.py`, `resolve_cpq_model_from_display_name`: with `cpq_model_scoped_questions_enabled` on, the
trademark / registered / copyright / service-mark signs are ignored when comparing a display name with the wording, and display
names are grouped by their comparable text, so `APX(TM) N50` and `APX N50` are one name and BOTH models of it are returned
(`APXN50`, `APXN50FLASHPORT`). Spacing inside a name is still significant (a catalog can map `APX3000` and `APX 3000` to
different models), the longest nested name still wins, and two unrelated names in one wording stay unresolved. Flag off: unchanged.
No model name in the code: the only literals are the mark characters.

### Flag note (review of #483)

The comparison is gated by `cpq_model_scoped_questions_enabled` on purpose (no new env var), so that flag now also decides how a
display name resolves for every caller of `resolve_cpq_model_from_display_name`: turning scoped questions off brings back the
mark-sensitive comparison. Its setting description says so.

## 5. Result (local, ws 281, the flags that reproduced it)

| | N50 | N30 |
|---|---|---|
| before | no band, no base model, asks Flashcode digits, power adapter, ... | complete, but band empty |
| after | complete, band 700/800 MHZ, base model `H25UCF9PW6AN`, 0 pending | complete, band 700/800 MHZ, `H15UCF9PW6AN` |

## 6. Limits

* Follow-up, not in this PR: the guard stays brittle for any other difference between the wording and `displayModel` (another word,
  a slash, a suffix). A guard-level safeguard (do not clear an attribute that separates the base models of a resolved model, or skip
  clearing when the resolved set looks incomplete) would cover that family of causes.

* A display name with a mark and a customer who spells the model differently (`APX-N50`, `APX N 50`) is not matched; not changed.
* The guard still asks about "the resolved models"; it now sees both models of the name. A catalog whose only rows for a model are
  the flashport rows keeps resolving to them (correct).
* Tests: `tests/test_cpq_display_name_trademark_marks_2026_10_08.py` (8): the key, both models returned with the flag, unchanged
  without it, a typed mark, spacing still significant, nested names, two unrelated names, and the guard's decision before/after.
* Existing tests (the 39 files that mention the display-name resolver, the guard or `data_table_product`): 331 pass, 1 fails
  (`test_raven_log_ask_steps_8_to_11::test_rule_eval_loop_exit_reasons`), which also fails on untouched `dev_oci` (it needs the
  Docker-internal Oracle host name from the machine running pytest).
