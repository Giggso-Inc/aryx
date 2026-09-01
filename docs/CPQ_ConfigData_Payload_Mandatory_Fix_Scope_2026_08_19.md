# CPQ `config_data` (JSON Preview Payload) — Fix Scope, Isolated to This One Consumer

**Date:** 2026-08-19
**Status:** Analysis + fix design only — no code changes made
**Scope:** deliberately narrowed to `build_payload(scope_required_and_edited=True)`'s
`config_data` output alone. Beautify and the summary are NOT touched by this doc — see
`docs/CPQ_Beautify_Mandatory_Section_Miscategorization_2026_08_19.md` for those.

## Recap of the Problem

A live `config_data` sample only contained 2 attributes:

```json
"configData": {
  "hWVersion_astro": {
    "value": "NEXT ENHANCED LTE PLUS 5G",
    "displayValue": "APX NEXT (4G LTE+5G)"
  },
  "productSelectionProduct_all": {
    "value": "APX NEXT ENHANCED",
    "displayValue": "APX NEXT Enhanced"
  }
}
```

Four confirmed, pure-user-input Mandatory fields with no catalog default were missing:
`ultimateDestinationCountry_astro`, `wirelessCarrier_astro`,
`modelSelectionFrequencyBandMsl_astro`, `isProvisioningRequiredInCloudEnv_astro`. Root cause
(fully detailed in `docs/CPQ_Beautify_Mandatory_Section_Miscategorization_2026_08_19.md`):
`build_payload`'s `_is_mandatory_input_attr` scoping only includes an attribute when it is a
structural anchor (Tier A), or matches a `"country"`/`"region"` name fragment AND has
`filled_source == "user"` literally (Tier B), or falls back to the same literal
`source == "user"` check with no name restriction. Any attribute resolved via `"hint"`,
`"cascade"`, `"cascade-dependent"`, or `"country_derived"` — all confirmed-genuine per-turn
decisions elsewhere in this same codebase (`_SUMMARY_ACTIVE_SOURCES`) — is silently excluded.

## Fix Scoped to `config_data` Only

**Revised (2026-08-19, same day): Tier C is deliberately NOT applied to `config_data`.**
`scope_required_and_edited`'s own docstring states the intent precisely: *"structurally-
required decision anchors plus attributes the customer directly answered... everything else
(cosmetic auto-fills, **blind-picked defaults**) is excluded."* Tier C (AttrSequence R-flag,
not curated-Recommended, not data-table-resolvable — designed for
`docs/CPQ_Beautify_Mandatory_Section_Miscategorization_2026_08_19.md`'s beautify fix) exists
specifically to catch **defaulted-but-never-touched** fields (Software Release, Solution
Type, Duration, Battery Type, Configuration Type, Application Services Bundle Duration).
Those are exactly the "blind-picked defaults" `config_data`'s own contract says must stay
excluded — applying Tier C here would directly contradict `scope_required_and_edited`'s
stated purpose. Tier C's rationale (the native UI still shows these as editable Mandatory-box
fields even when defaulted) is valid for beautify, which mirrors what the customer visually
sees, but not for `config_data`, whose narrower job is only what was structurally forced or
genuinely decided.

**One change only**, applied ONLY at the `build_payload(scope_required_and_edited=True)` call
site — beautify's and the summary's own `_is_mandatory_input_attr` calls are left exactly as
they are today, and no Tier C infrastructure is needed for this fix at all:

1. **Widen the bare fallback's source check** from the single literal `source == "user"` to
   a new, `config_data`-specific active-source set: `{"user", "hint", "cascade",
   "cascade-dependent", "country_derived", "product_anchor"}`. This is `_SUMMARY_ACTIVE_
   SOURCES` (`engine.py:12123`) **minus `"rule"`** — deliberately excluded here, since a
   fired-rule value (e.g. Package Type resolving via the ICE-Kit `RecommendationRule`) is
   exactly the "cosmetic auto-fill" `config_data` must keep excluding, even though the
   summary's own docstring treats "a rule whose condition actually held" as active for ITS
   different purpose. Excludes passive `"rule"`/`"default"`/`"auto"` fills deliberately —
   those are catalog-computed, never a real decision, and must stay out of `config_data`.

This alone fixes all four originally-missing attributes: Country/Provisioning are `"hint"`-
sourced, Carrier/Frequency Band Msl are `"cascade"`/`"cascade-dependent"`-sourced — none of
them need Tier C at all.

This makes Tier B redundant for `config_data` specifically (the widened bare fallback already
covers every name, not just `"country"`/`"region"`) — Tier B can be left in place unchanged
(harmless overlap) or simplified away; either is a valid implementation choice, not a
correctness requirement.

`build_payload`'s existing, separate exclusions (`hidden_vns` from active hiding rules,
`hide_in_trans`, `set_type == "2" and not auto_lock`) remain fully in effect underneath this —
this fix doesn't touch them, so master-string/help-text/QR-code/array-control noise stays
excluded exactly as it is today.

## Resulting `config_data` — Worked Example Against the Live Transcript

Using the same live transcript's full filled state (the one whose `beautify`/`summary` output
was reviewed earlier this session — `aSTRO25_bom` / APX NEXT Enhanced / `H55TGT9PW8BN`), here
is every attribute that WOULD appear in `config_data` once the fix is applied, and why —
followed by the ones that would still correctly stay excluded.

### Included

| Attribute | Value (from the transcript) | Included via |
|---|---|---|
| `productSelectionProduct_all` | APX NEXT Enhanced | Tier A (structural anchor) |
| `hWVersion_astro` | APX NEXT (4G LTE+5G) | Tier A (structural anchor) |
| `modelSelectionbaseModel_astro` | H55TGT9PW8BN | Tier A (`"basemodel"` fragment) |
| `ultimateDestinationCountry_astro` | United States | Widened bare fallback (`source="hint"`, confirmed live) |
| `wirelessCarrier_astro` | (unfilled/invalid in this transcript — would appear once validly filled) | Widened bare fallback (`source="cascade"`/`"cascade-dependent"`) once resolved |
| `carrierSelectionMultiSelect_astro` | ATT/FirstNet (provided by Motorola) | Widened bare fallback (`source="cascade"`/`"cascade-dependent"` or `"user"`) |
| `modelSelectionFrequencyBandMsl_astro` | (value not directly shown in this transcript's beautify dump, but confirmed cascade-reachable from Hardware Version) | Widened bare fallback (`source="cascade-dependent"`) |
| `isProvisioningRequiredInCloudEnv_astro` | No | Widened bare fallback (`source="hint"` or `"user"`) — also fixes the separate boolean-drop issue documented in the beautify doc, since `build_payload` never applied `_is_summary_excluded`'s boolean check in the first place |

### Correctly Excluded (unchanged by the fix)

| Attribute | Why it stays out |
|---|---|
| `packingPackageType_astro` (Package Type) | `source="rule"` — a fired-rule value is exactly the "cosmetic auto-fill" the widened set (which excludes `"rule"`) keeps out |
| `configurationType`, `softwareBundlesBundleType_astro`, `baselineReleaseSW_astro`, `solutionTypeDevices_astro`, `solutionTypeDuration_astro`, `applicationServicesIntroBundle_astro`/`applicationServicePromotionalDuration_astro`, `applicationServicesSelection_astro`, `batteryType_astro` | Genuinely never-edited catalog defaults in this transcript (`source` is `"rule"`/`"default"`, not an active-decision tag) — deliberately NOT promoted via Tier C per the revised design above. These still correctly appear in beautify's Mandatory section once that separate fix lands, since beautify's job (mirror the native UI) differs from `config_data`'s job (only genuine decisions) |
| `antennasType_astro`, `beltClipType_astro`, `advancedSystemKeyHardwareKey_astro`, `deviceManagementTraining_astro`, `dmsDuration_astro`, `documentationTestResultsRatedAudioPrintoutLabel_astro`, `serviceTypeAdditionalDMSCoverage_astro`, `systemEnhancementFeatureType_astro`/`additionalSystemEnhancementFeatureType_astro` | Curated Recommended-Configuration-only set (also `source="rule"` in practice) |
| `hiddenConstraintMasterString_astro`, `hiddenConstraintMasterStringForBaseModel_astro`, `hiddenMasterStringForAstroPortable_astro`, `hiddenMasterStringForNonFrequencyParametricData_astro`, `hiddenUISequenceForModelSelection_astro`, `hiddenUISequenceMasterString_astro`, `defaultAttrValuesMasterString_astro` | Internal master-string noise — excluded by `build_payload`'s existing `hide_in_trans`/`set_type` checks, untouched by this fix |
| Every `...HelpText_astro`/`...Helptext_astro` variant (`isProvisioningRequiredInCloudEnvHelpText_astro`, `smartIncidentHelpText_astro`, `packageTypeHelpText_astro`, etc.) | Same — never a real customer decision, excluded by the same existing checks |
| `cBPQRCode_astro`, `fedQRCode_astro`, `dataTableList_astro`, `ccArrayControl_astro`, `provAgenArrayControl_astro` | Same — internal/array-control plumbing, not catalog decisions |

## What This Fix Deliberately Does NOT Change

- Beautify's "Mandatory User Input" vs. "System-Configured / Recommended" split — untouched.
  If the same Tier C + widened-source fix is wanted there too, that is the scope of
  `docs/CPQ_Beautify_Mandatory_Section_Miscategorization_2026_08_19.md`'s own plan, a
  separate implementation step.
- The conversational summary's item selection — untouched, same reasoning.
- Any real BOM submission — `build_payload`'s `scope_required_and_edited=True` branch is,
  per its own existing docstring, deliberately never wired into the real-submission call
  path; only the JSON-preview response passes `True`. This fix only changes what the preview
  shows, never what gets submitted.

## Implementation (2026-08-19)

Implemented as a narrowly-scoped patch touching only `_is_mandatory_input_attr` and the two
`build_payload` call sites that use it with `scope_required_and_edited=True`:

- New constant `_CONFIG_DATA_ACTIVE_SOURCES = frozenset({"user", "hint", "cascade",
  "cascade-dependent", "country_derived", "product_anchor"})` in `engine.py` — `_SUMMARY_
  ACTIVE_SOURCES` minus `"rule"`, for the reason explained above.
- `_is_mandatory_input_attr` gained a new optional `active_sources: frozenset[str] | None =
  None` parameter. `None` (the default) preserves the exact literal `source == "user"` check
  for every existing caller (beautify, the summary) byte-for-byte. `build_payload`'s two call
  sites now pass `active_sources=self._CONFIG_DATA_ACTIVE_SOURCES`.
- No Tier C, no new resolver, no new DB round-trip — this was a same-file, same-function,
  additive-only change.

## Known Gap (Not Yet Fixed): Tier A Over-Includes `modelSelectionbaseModel_astro`

Live-confirmed against a real target `config_data` payload (Oracle CPQ's own expected shape)
that this catalog's actual submission needs exactly 5 attributes:

```json
"configData": {
  "ultimateDestinationCountry": {"value": "US", "displayValue": "United States"},
  "hWVersion_astro": {"value": "NEXT STANDARD LTE ONLY", "displayValue": "APX NEXT (4G LTE Only)"},
  "productSelectionProduct_all": {"value": "APX NEXT MULTI", "displayValue": "APX NEXT All Band"},
  "isProvisioningRequiredInCloudEnv_astro": {"value": "NO", "displayValue": "No"},
  "wirelessCarrier_astro": {"value": "ATT/FIRSTNET", "displayValue": "ATT/FirstNet (provided by Motorola)"}
}
```

`modelSelectionbaseModel_astro` (Base Model) is **not** in this real target payload, and does
**not** appear in the native UI's "Mandatory User Input" box either — yet today's Tier A
includes it unconditionally (its variable name fragment-matches `"basemodel"`), so it still
ships in `config_data`.

### Root cause — confirmed via the real ConfigAttr row

```json
{
  "name": "Base Model",
  "hidden": "0",
  "hide_in_trans": "0",
  "set_type": "3",
  "menu_type": "1",
  "variable_name": "modelSelectionbaseModel_astro"
}
```

Note the casing mismatch between source tables: AttrSequence's own `AttrName` column stores
this as `modelSelectionBaseModel_astro` (capital "B"), while the real ConfigAttr
`variable_name` is `modelSelectionbaseModel_astro` (lowercase "base") — confirmed both refer
to the same attribute (`id: 17691442356`, `name: "Base Model"`).

`menu_type: "1"` — at the catalog level this looks like a genuine menu-type attribute with
real options, and none of `build_payload`'s existing exclusions (`hidden`, `hide_in_trans`,
`set_type == "2"`) apply to it. But functionally, its value is **100% derived** from Country +
Hardware Version + Product via the ingested `NewCountryRegMapping` (region-rule-shaped) Data
Table — `data_table_resolver.resolve_region_allow_value`'s own docstring names
`modelSelectionbaseModel_astro` as its worked example: for a given `(CPQModel, region)`, that
table resolves it to exactly one `ALLOW` value. It is never an independent customer decision —
this is Shylaja Shetty's own "Auto-Resolved by Data Tables" category (the same class Package
Type belongs to), just also caught by Tier A's unconditional name-fragment match.

### Why Tier A over-includes it

`_is_mandatory_input_attr`'s Tier A treats any `"basemodel"`/`"selectmodel"`-fragment-matched
attribute as a structural anchor unconditionally — no data-table-coverage check at all, unlike
Tier C (which already excludes anything `resolve_whitelist_values` confirms is Whitelist/
Defaultinattr-resolvable). Tier A was designed for catalogs where "Select Model"/"Base Model"
genuinely is a customer-facing dropdown decision; for this catalog it is fully data-table-
resolved instead, so the blanket fragment match is too broad here.

### Generic fix (not implemented — no hardcoded exception for this one variable name)

Give Tier A the same discipline Tier C already has: before treating a `"basemodel"`/
`"selectmodel"`-fragment match as a structural anchor, additionally check
`data_table_resolver.resolve_region_allow_value` (or the broader region-rule table) for real
coverage of that attribute under the active `(cpq_model, region)` — if a region-rule row
already fully and deterministically resolves it, it is not a genuine anchor decision and
should not qualify via Tier A. This is driven entirely by real ingested Data Table coverage
(the same discipline as Tier C and the rest of this session's work), not a hand-listed
exception — it would also correctly generalize to any OTHER catalog where an equivalent
"basemodel"/"selectmodel" attribute is genuinely data-table-resolved rather than customer-
facing.

### Impact Scope — Which Attributes This Would Actually Touch

**Only the `"basemodel"`/`"selectmodel"` fragment branches of Tier A** — the other two Tier A
branches are untouched by this fix:

```python
tier_a = attr is not None and (
    vn == "productSelectionProduct_all"        # exact match -- untouched
    or self._is_hardware_version_attr(attr)    # separate helper -- untouched
    or "basemodel" in vn_flat                   # <- fix targets this
    or "selectmodel" in vn_flat                 # <- fix targets this
)
```

Product and Hardware Version are unaffected either way — they stay included regardless.
Within the `basemodel`/`selectmodel` branches, an attribute is removed from Tier A only if it
*also* has confirmed region-rule coverage (`resolve_region_allow_value` resolves it) — that's
currently just `modelSelectionbaseModel_astro` for this catalog, but the check is fragment-
based and data-table-driven, not a hardcoded single-variable exception, so it would correctly
generalize to any other `basemodel`/`selectmodel`-named attribute (this catalog or another)
that turns out to be similarly data-table-resolved. A genuinely customer-facing "Select
Model"/"Base Model" dropdown (no region-rule coverage) would still correctly qualify via Tier
A — this fix narrows, it does not remove the branch's purpose.

**Related leak spotted while checking this, NOT covered by the proposed fix**:
`hiddenConstraintMasterStringForBaseModel_astro` also contains the substring `"basemodel"`
(`"...forbasemodel_astro"`), so it currently matches Tier A's fragment check too, even though
it's an internal master-string attr (`hidden: "1"`), never a real Base Model field. The
region-rule-coverage check likely would NOT exclude it (master-strings aren't rows in
`NewCountryRegMapping`), so it would need a separate check if it isn't already caught earlier
by `build_payload`'s `_is_noise_var` filter — not yet confirmed either way.

**Scoped to Tier A only — Tier B and Tier C are untouched.** Tier B (country/region fragment +
active source) and Tier C (AttrSequence R-flag + Whitelist/Defaultinattr coverage) are
separate mechanisms this fix does not modify.

**Cross-consumer consequence**: unlike Tier C (which `config_data` deliberately never
receives) and the active-source widening (`config_data`-only, gated by `active_sources`),
**Tier A has no per-consumer gate at all today** — the same unconditional check for every
caller of `_is_mandatory_input_attr`. Implementing the region-rule check unconditionally
would therefore change all three consumers at once (Base Model would also leave beautify's
Mandatory section and the summary), which is broader than this document's own scope.

### Revised Design — Scoped to `config_data` Only (mirrors Tier C's `required_vns` pattern)

Per instruction, this fix is scoped the same way Tier C already is: an opt-in exclusion set,
`None` by default so beautify and the summary are byte-for-byte unaffected, passed only from
`build_payload`'s two `config_data` call sites.

1. **New helper**, `CpqEngine._data_table_resolved_anchor_vns(filled, workspace_id,
   catalog_prefix, cache)` — the mirror image of `mandatory_tier_c_vns`, but an EXCLUDE set
   for Tier A rather than an INCLUDE set for Tier C. For each candidate `cpq_model` (resolved
   the same way `mandatory_tier_c_vns`/`_suppress_ungoverned_attrs` already do) and the
   active region, checks `resolve_region_allow_value(attr_var_name, cpq_model, region,
   workspace_id, catalog_prefix, cache)` for every attribute whose name fragment-matches
   `"basemodel"`/`"selectmodel"` among `attrs` — if it resolves to exactly one value, add that
   variable name to the exclude set. Returns `frozenset()` (never `None`) when `filled`/
   `workspace_id`/region are unavailable — purely subtractive, so "no coverage" must mean "no
   exclusions," matching Tier C's own safety convention.
   - **Region source**: `filled.get("modelSelectionRegion_astro", "")` — this is itself one of
     the AttrSequence-Required attributes already confirmed live (part of the 44 R-flagged
     names for APXNEXT*), typically resolved from Country before Base Model is reached. Empty
     region → empty exclude set (no-op), never a guess.
2. **`_is_mandatory_input_attr` gains a second new parameter**, `exclude_anchor_vns:
   frozenset[str] | None = None` (default `None`, preserving Tier A's current unconditional
   behavior for every existing caller byte-for-byte). The `"basemodel"`/`"selectmodel"`
   fragment checks become:
   ```python
   or ("basemodel" in vn_flat and vn not in (exclude_anchor_vns or frozenset()))
   or ("selectmodel" in vn_flat and vn not in (exclude_anchor_vns or frozenset()))
   ```
   Product's exact-match branch and the separate Hardware Version branch are untouched, same
   as the unscoped design above.
3. **`build_payload` needs two new parameters it doesn't have today**: `workspace_id: int |
   None = None` and `catalog_prefix: str = ""` (both default-safe, no existing caller passes
   them so behavior is unchanged unless explicitly supplied). Its two `config_data` call
   sites (the flat `filled` loop and the `filled_multi` loop) compute
   `exclude_anchor_vns = self._data_table_resolved_anchor_vns(filled, workspace_id,
   catalog_prefix)` once at the top of the method (only when `scope_required_and_edited` is
   True, to avoid the resolver cost otherwise) and pass it into both
   `_is_mandatory_input_attr` calls.
4. **`ask_api.py`'s single `build_payload(..., scope_required_and_edited=True)` call site**
   (the JSON-preview builder, `ask_api.py:11518` area) passes `workspace_id=req.workspace_id,
   catalog_prefix=catalog_prefix` — both already resolved and in scope there, exactly as they
   already are for the `active_sources`/`_CONFIG_DATA_ACTIVE_SOURCES` fix.

With this scoping, beautify's Mandatory/Recommended split and the summary's item list are
completely unaffected — Base Model would drop out of `config_data` alone, exactly like the
other two fixes in this document.

**Status: Implemented (2026-08-19).** `CpqEngine._data_table_resolved_anchor_vns` (the
config_data-only exclude set), `_is_mandatory_input_attr`'s new `exclude_anchor_vns`
parameter, and `build_payload`'s new `workspace_id`/`catalog_prefix` parameters (all default-
safe — no existing caller's behavior changes unless explicitly opted in) are shipped. All 3
`ask_api.py` call sites that pass `scope_required_and_edited=True` now also pass
`workspace_id=req.workspace_id, catalog_prefix=catalog_prefix`. 7 new tests
(`test_cpq_config_data_basemodel_anchor_exclusion_2026_08_19.py`) cover the exclusion, the
Product/Hardware-Version-unaffected guarantee, `_data_table_resolved_anchor_vns`'s empty-input
safety, and the legacy (no `workspace_id`) byte-for-byte-unchanged path. Full CPQ+BML suite:
same 16 pre-existing failures, 1256 passing (up from 1249).
