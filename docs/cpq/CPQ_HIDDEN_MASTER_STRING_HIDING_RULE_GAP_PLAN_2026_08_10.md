# Compute `hiddenMasterStringForAstroPortable_astro` Natively — Plan

## Context

A systematic sweep of the APX Next / ApxnextConfigdata catalog (workspaces 3, 39004, 39005 —
identical rule data) found 31 real, layout-visible attributes being asked or shown to every
customer regardless of whether the underlying business rule would actually hide them:
`wirelessCarrier_astro`, `modelSelectionFrequencyBandPlus_astro` ("Additional Frequency Bands"),
`extendRangeTo762764MHz_astro`, `modelSelectionHousing_astro`, `antennasType_astro`,
`batteryType_astro`, `beltClipType_astro`, and 24 more (full list in
`CPQ_Auto_Fill_and_Hiding_Rules_RCA.docx`, revision 2 at the time — now revision 5).

All 31 trace to exactly one shared cause. Each one's hiding rule is a BigMachines script that
checks membership in a helper variable — `hiddenMasterStringForAstroPortable_astro` (30 of the
31) or a sibling, `hiddenHidingRuleMasterString` (the remaining one,
`modelSelectionFrequencyBands_astro`). That variable is supposed to be computed by one
recommendation rule, "Set Hidden Master String For Astro Portable" — but that rule's script is a
genuinely complex, table-driven computation (uses `Recordset()`, dynamic `attrSequence` table
lookups, JSON parsing of `dataTableList_astro`) that Aryx's `BmlEvaluator` (Tier-1 deterministic
parser + Tier-2 LLM fallback) cannot resolve. Confirmed live: running the real evaluator against
the real script and a real conversation's actual `filled` state returns `None` ("unknown"), and
`hiddenMasterStringForAstroPortable_astro` is confirmed absent from real `filled` state. This is
NOT a missing-data problem — `bmfunction` script records are fully present and were directly
read (400-700+ characters each, non-empty) — it is an evaluation gap.

**The key discovery driving this plan:** the *core algorithm* the BM script performs — look up
which attribute names apply to the current product-model/base-model pair in the `attrSequence`
dynamic table — is **already implemented, already generic, and already wired into a different
part of this codebase**: `data_table_resolver.governed_attr_names_for_base_model()`, used today
by `CpqEngine._suppress_ungoverned_attrs`. This plan wires that existing capability into the one
missing variable, rather than rebuilding a BM-script interpreter.

## Approach

Add one new `CpqEngine` method, `_compute_hidden_master_string(filled, workspace_id,
catalog_prefix, cache=None) -> str | None`, in `src/aryx/cpq/engine.py`, next to
`_suppress_ungoverned_attrs` (~line 5360) since it reuses the exact same inputs:

1. Read `product = filled.get("productSelectionProduct_all", "")` and
   `base_model = filled.get("modelSelectionbaseModel_astro", "")`. Return `None` immediately if
   either is empty — mirrors `_suppress_ungoverned_attrs`'s own no-op guard, and matches the real
   script's own behavior (it needs both to do a meaningful lookup).
2. Get candidate CPQModel codes via the **already-existing** `_cpq_model_candidates(product,
   workspace_id, catalog_prefix, cache, base_model=base_model)` (engine.py ~line 671) — the same
   call `_suppress_ungoverned_attrs` already makes.
3. For each candidate, call the **already-existing, already-generic**
   `data_table_resolver.governed_attr_names_for_base_model(cm, base_model, workspace_id,
   catalog_prefix, cache)` (imported at the top of `engine.py` as
   `dt_governed_attr_names_for_base_model`) and union the results — same pattern as
   `_suppress_ungoverned_attrs` (~lines 5415-5422). Return `None` if every candidate returns
   `None` (no sequence-table coverage at all for this attribute-independent lookup) — leave the
   downstream hiding scripts in their current "unknown" state rather than fabricate an empty
   string, since an empty string would make the script's `findinarray(...) == -1` branch fire
   and hide everything unconditionally.
4. Join the resulting name set with the real separator value — read
   `filled.get("hidddenRecordSeparator_allFamilly")`, falling back to the attribute's own real
   catalog `default_value` (`'@@@'`, confirmed live) — matching the real script's own
   `returnVal = returnVal + get(data,"AttrName") + recSep` construction exactly.

**Wiring:** in `evaluate_rules_loop` (engine.py ~3860), immediately before hiding rules are
applied each pass, if `"hiddenMasterStringForAstroPortable_astro"` is not already present in
`filled`, compute it via the new method and inject it into the working `filled` dict passed to
`apply_hiding_rules`. Never override an explicit/real value if one somehow already exists. This
is a single wiring point — every caller of `evaluate_rules_loop` benefits automatically, the same
pattern already used for `display_order` and `rule_conflict_order` earlier this session.

**The sibling variable** (`hiddenHidingRuleMasterString`, used only by
`modelSelectionFrequencyBands_astro`'s hiding rule): verify during implementation whether its own
upstream computation rule follows an equivalent `attrSequence`-lookup shape. If so, handle it the
same way in the same method (parameterized by variable name); if its script differs
structurally, scope it out as a separate, smaller follow-up rather than force-fitting it.

## Critical files

- `src/aryx/cpq/engine.py` — new `_compute_hidden_master_string` method; one new call site in
  `evaluate_rules_loop`. Reuses `_cpq_model_candidates` (existing, ~line 634) and
  `dt_governed_attr_names_for_base_model` (already imported).
- `src/aryx/cpq/data_table_resolver.py` — no changes expected; read-only reuse.
- `tests/test_cpq_hidden_master_string.py` (new) — unit tests against synthetic
  `attrSequence`-shaped fixtures.

## Explicitly out of scope for this pass

A handful of the 31 attributes layer an *additional* real business condition on top of the
generic "is this in the sequence table" check: `extendRangeTo762764MHz_astro` (Federal/privileged
customers only), `cBPQRCode_astro`/`fedQRCode_astro`/`dHSAssetTagLabel_astro` (specific customer
group), `modelSelectionHousing_astro` (XE-model only). Computing the master string correctly only
fixes their "is this even in scope" gate — their extra condition is a separate, smaller
follow-up once the master string itself is flowing correctly and can be re-assessed against real
data.

## Verification

1. **Unit tests** (synthetic, catalog-agnostic fixtures — no hardcoded catalog specifics):
   attribute present in the sequence table for the resolved (cpqModel, baseModel) → included in
   the joined string; attribute absent for this base model but present for another → excluded;
   no sequence coverage at all for any candidate → method returns `None` (untouched, not an
   empty string); separator value correctly read from `filled` or falls back to the real default
   `'@@@'`.
2. **Live verification against the real container** (workspace 39005, same discipline used
   throughout this investigation): replay the "APX NEXT All Band" conversation used during
   diagnosis, confirm `hiddenMasterStringForAstroPortable_astro` is now populated in `filled`
   once Base Model resolves, and confirm at least 3-4 of the 31 attributes (Wireless Carrier,
   Additional Frequency Bands, Extend Range, Antenna Type) now correctly hide or stay visible
   matching the real business condition — via `aryx_rule_trace_entry` showing real `hide`/`show`
   outcomes instead of zero trace rows.
3. **Regression check**: re-run the full `-k cpq` suite (`PYTHONPATH=src`, same known
   pre-existing failures excluded — confirmed earlier this session via `git stash` comparison) to
   confirm no existing behavior breaks, especially `_suppress_ungoverned_attrs`, which shares
   inputs with the new method.
4. Rebuild (`docker compose -f docker-compose.local.yml build api`), redeploy
   (`up -d --force-recreate --no-deps api`), and live-verify one more time before considering
   this done.
