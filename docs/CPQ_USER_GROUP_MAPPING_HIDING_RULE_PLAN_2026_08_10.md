# UserGroupMapping Support — Plan

## Context

Following the `hiddenMasterStringForAstroPortable_astro` fix
(`CPQ_HIDDEN_MASTER_STRING_HIDING_RULE_GAP_PLAN_2026_08_10.md`), 3 of the remaining flagged
attributes — `cBPQRCode_astro`, `fedQRCode_astro`, `dHSAssetTagLabel_astro` — still show up for
every customer. Their real hiding rule ("Hide DHS Asset tag label and CBP qr code unless part of
APXRADIOs9YRS customer group") depends on a genuinely different signal than the master-string
fix: it checks the current order's `customerUIN` (a real, knowable, customer-level identifier —
not a session/rep variable) against a dynamic `UserGroupMapping` data table, filtered to a named
customer group:

```
customersRecords = bmql("select id_name from UserGroupMapping where group_name = 'APXRADIOS9YRS'");
for eachRecord in customersRecords{
    customerNumber = get(eachRecord,"id_name");
    append(customerNumbersArr,customerNumber);
}
if(findinArray(customerNumbersArr,customerUIN) <>-1){
   return false;   // customer is in the group -> show
}
return true;         // else -> hide
```

Unlike `attrSequence` (already ingested and resolved generically via
`data_table_resolver.governed_attr_names_for_base_model`), **`UserGroupMapping` is not currently
ingested anywhere** — confirmed live by listing all 75 real ingested entity types for workspace
39005; zero matches for anything group-mapping-shaped. This plan is therefore two-part: a small,
generic code addition, and an explicit data dependency that engineering cannot resolve alone.

## Approach

`data_table_resolver.py` already generalizes by table SHAPE (column signature), not name or
per-catalog logic — its own module docstring states new rule/table combinations need zero new
code as long as they match one of the four existing shapes (`constraint`, `sequence`,
`hierarchy`, `region_rule`), detected via `_SHAPE_DETECTORS`. `UserGroupMapping`'s real columns
(`id_name`, `group_name`) are disjoint from all four — this needs one new, additive shape.

1. Add `_is_user_group_mapping_shaped(keys: set[str]) -> bool` to `data_table_resolver.py`,
   alongside the existing four detectors (~line 95-130): `return "id_name" in keys and
   "group_name" in keys`.
2. Register it in `_SHAPE_DETECTORS` (~line 135) and extend `_load_all_tables`'s return tuple to
   include the new table's rows, following the exact same pattern the other four shapes already
   use (each gets its own slot in the cached tuple returned by `_load_all_tables`).
3. Add one new resolver function, `customer_in_user_group(customer_uin: str, group_name: str,
   workspace_id: int, catalog_prefix: str = "", cache: dict | None = None) -> bool | None`:
   filters the new table's rows to `group_name` matches, collects `id_name` values, returns
   whether `customer_uin` is among them. Returns `None` (not `False`) when there is no
   UserGroupMapping coverage at all — mirrors every other resolver's "silence is not a confident
   answer" discipline (`governed_attr_names_for_base_model`, `resolve_region_allow_value`, etc.).
4. Wire this into `CpqEngine`, following the exact shape of `_compute_hidden_master_string`:
   a small helper that, given `filled.get("customerUIN")`, computes whether the customer belongs
   to the specific group each affected hiding rule's script checks, and exposes that as a
   variable the hiding-rule scripts can read — OR, given there are only 3 affected attributes
   sharing one exact script pattern, consider special-casing via the same
   `BmlEvaluator.hide_for_script` path once the underlying data exists (Tier 1 may already parse
   this script's `if/return` shape correctly, the same way it already handles Housing's
   XE-model check — verify this BEFORE building a bespoke bypass).

## Critical files

- `src/aryx/cpq/data_table_resolver.py` — new shape detector, one new resolver function,
  `_load_all_tables` return-tuple extension.
- `src/aryx/cpq/engine.py` — small wiring addition once the resolver function exists (exact
  shape TBD by step 4's Tier-1 verification).
- `tests/test_cpq_data_table_resolver.py` — new tests for the shape detector and resolver
  function, using synthetic fixtures (same `_patch_rdb` pattern used throughout this codebase).

## The real blocker — data, not code

**This is the load-bearing constraint of this whole plan.** The code above can be written and
unit-tested against a synthetic fixture today. It cannot be verified against real behavior, and
will not change anything for real customers, until a `UserGroupMapping` (or an equivalently
`id_name`/`group_name`-shaped) CSV export is actually ingested for the relevant workspace(s)
through the normal ingestion flow. This is not an engineering estimate gap — it's a genuine
dependency on someone locating and uploading that data file from the source BigMachines export.
Recommend confirming this data exists and getting it queued for ingestion before investing
implementation time here, so the fix can be live-verified the same way every other fix in this
investigation has been (real container, real rule-trace data) — not left as an untested,
synthetic-only change.

## Verification (once data is available)

1. **Unit tests**: shape detector correctly classifies a synthetic `UserGroupMapping`-shaped
   table; `customer_in_user_group` returns `True`/`False`/`None` correctly across in-group,
   out-of-group, and no-coverage-at-all cases.
2. **Live verification**: after the real CSV is ingested, replay a conversation for a customer
   confirmed to be (and one confirmed NOT to be) in the `APXRADIOS9YRS` group, and confirm
   `cBPQRCode_astro`/`fedQRCode_astro`/`dHSAssetTagLabel_astro` correctly show/hide via real
   `aryx_rule_trace_entry` rows, the same discipline used for the master-string fix.
3. **Regression check**: re-run the full `-k cpq` suite; confirm the 4 existing shape detectors
   and their resolver functions are untouched and still pass.
