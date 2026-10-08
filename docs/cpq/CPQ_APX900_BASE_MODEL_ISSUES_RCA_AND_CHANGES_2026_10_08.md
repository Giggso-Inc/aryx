# APX 900 (ws 1267, Astro25): issues, root causes, changes, evidence

Date: 2026-10-08. Workspace 1267, catalog prefix `Astro25Configdata`. Pull request: #478 (replaces #474 and #477; follows
#473 and #475). Companion doc with the design and rollout: `CPQ_BASE_MODEL_NARROWING_IMPLEMENTATION_2026_10_08.md`.

Flow under test: **"I want a quote for APX 900 in the US"**. The customer must never be asked for the base model from 660 options.
Ask frequency band and keypad type (the attributes that separate the model's base models), list only the values the model
holds (5 bands, 2 keypads), derive the base model from the answers, and ask only what the real screen asks.

Status of the evidence: every number below comes from your DBeaver queries, your docker logs, your screenshots and the sheet
`APX 4500 Enhanced Configurations V6.xlsx`. Nothing was run by me against dev. "Verified" means seen in that evidence;
"not verified" says so.

---------------------------------------------------------------------------------------------------------------------------

## 1. Summary

| # | Issue | Root cause (one line) | Fix | Status |
|---|---|---|---|---|
| 1 | Base model asked from 660 options | frequency / keypad were guessed or unknown, so the derivation had nothing to narrow with | #473 (merged): ask the separating attributes first, derive the base model | fixed, needs replay |
| 2 | Frequency / keypad lists show 20 / 4 options | the catalog menu was shown in full; the whitelist holds 5 / 2 | #478: limit the question to the model's own values | in #478 |
| 3 | Keypad asked before frequency | question order came from layout / catalog order; the model's own sequence is frequency 33, keypad 39 | #478: order the narrowing questions by attrSequence `Seq` | in #478 |
| 4 | "700/800 MHz" typed in the first message is dropped | hints run before the turn's model is bound; Product is not filled on the first message | #478: resolve the model from the wording in the hint step | in #478 |
| 5 | Both answers given, base model still asked | country US applied first dropped the two 700/800 base models (10 -> 8); country only appears as a condition of other attributes' rows | #478: separating attributes first; condition-only attributes do not narrow | in #478 |
| 6 | 7 quantity holders asked after auto-fill finished with 0 pending (APX N30) | the grid step seeds every option of a selector that has no selection, pending or not | #478: seed only selectors the pass left pending | in #478 |
| 7 | Product stored as `APX900FLASHPORT` | the catalog's only "APX 900" Product item is the flash-upgrade series | not changed | open |
| 8 | Antenna, hazardous location, package, belt clip are first-option guesses | the `Defaultinattr` table holds the real defaults but the flag that reads it is off | set `ARYX_CPQ_DEFAULTINATTR_SHAPE_ENABLED` (no code) | needs env + replay |
| 9 | Battery shows 2900 mAh, sheet allows only 3000 mAh (Standard) | a consequence of the guessed hazardous location: `TIA4950(UL)` allows only 2900 mAh | fixed by #8; the default among the remaining 5 is still a guess | partly open |
| 10 | Encryption Type is never asked | required by a TER-gated blank-disallow rule, optional in attrSequence; Ask never read the derived required set | #478: ask the derived required set (flag) | in #478 |
| 11 | APX 8000H `DERIVED_CODE_NOT_AN_OPTION` | most likely the part-number attribute `modelSelectionBaseModelMsl_astro` (46 options) | not changed | not verified |

Pull requests: #473 merged (narrowing), #475 merged (N30 / N50 model scoping), #474 and #477 closed in favour of #478.

---------------------------------------------------------------------------------------------------------------------------

## 2. Data facts (query results)

### 2.1 Whitelist: base model, band, keypad (`WS1267_WHITELIST`, `CPQModel = 'APX900'`)

Every base model holds one band (`ATTR1`) and one keypad (`ATTR2`). Region (`ATTR3`) lists EA, LA, ME, NA, AP for each.

| Base model | Band | Keypad |
|---|---|---|
| H92KDF9PW6AN / H92KDH9PW7AN | VHF | LIMITED KEYPAD / FULL KEYPAD |
| H92QDF9PW6AN / H92QDH9PW7AN | UHF R1 | LIMITED / FULL |
| H92SDF9PW6AN / H92SDH9PW7AN | UHF R2 | LIMITED / FULL |
| H92UCF9PW6AN / H92UCH9PW7AN | 700/800 MHZ | LIMITED / FULL |
| H92WCF9PW6AN / H92WCH9PW7AN | 900 MHZ | LIMITED / FULL |

Code letters: `F` = Limited Keypad, `H` = Full Keypad; band letters K, Q, S, U, W as above. The two 700/800 base models also carry
a row `Housing = GREEN, Keypad, Frequency, Country = BR`.

Separating-attribute check (distinct values per base model, normalised with `UPPER(TRIM())`): 20 rows (2 attributes x 10 base
models), every `n_values = 1`. The first version of this query returned nothing because of its `HAVING` clause, not the data.

### 2.2 attrSequence order

`WS1267_ATTRSEQUENCE`: `modelSelectionFrequencyBands_astro` Seq **33**, `modelSelectionKeypadType_astro` Seq **39**, for all 10 base
models. (The EDA export in this repo lists the same order: Frequency 33, Keypad 39, Base Model 42.)

### 2.3 Where country appears in the whitelist (APX900)

Country is never a target (`ATTR1`). It is only a condition (`ATTR2`..) of rows about other attributes:

| Base models | Target attribute | Country conditions seen |
|---|---|---|
| K, Q, S (F and H) | `systemEnhancementFeatureType_astro` | US ("Delete narrowbanding, waiver required"), MX ("Tactical services") |
| W (F and H) | not visible in the query output (it showed slots 1-2 only) | inferred, not seen: the derivation log reports 8 of 10 base models matching US, which the 6 K/Q/S models above plus these 2 would explain |
| UCF, UCH (700/800) | `languageLanguageType_astro`, `modelSelectionHousing_astro`, `systemEnhancementFeatureType_astro` | **BR and MX only, never US** |

### 2.4 Models and hierarchy

`WS1267_BASEMODELTOCONFIG` (APX 900 and APX 8000H):

| Display | CPQ model | Variable | Base models |
|---|---|---|---|
| APX 900 | APX900 | aPX900 | the 10 `H92...` codes |
| APX 900 FLASHPORT | APX900FLASHPORT | aPXFLASHportSeries | T8523A, T8524A, T8525A, T8526A |
| (APX 8000H) | APX8000H | | H91TGD9PW8AN, H91TGD9PW9AN |
| | APX8000HSRX | | H91TGD9PW4AN, PW8AN, PW9AN |
| | APX8000HXE | | H91TGD9PW4AN, PW8AN, PW9AN |
| | APX8000H / HSRX / HXE FLASHPORT | | T8549A, T8550A, T8553A, T8554A, T8627A |

`WS1267_CPQMODELHIERARCHY` (APX 900):

| CPQMODELNAME | PRODUCT | DISPLAYCPQMODEL | CPQMODELVARIABLENAME |
|---|---|---|---|
| APX900 | (blank) | APX 900 | aPX900 |
| APXFLASHPORTSERIES | APX900FLASHPORT | APX 900 FLASHport | aPXFLASHportSeries |

`WS1267_WHITELIST` model base-model count: `APX900` = 11 (10 base models plus `ALL`); `APX900FLASHPORT` has **no rows**.
`WS1267_FLAGSFORFLASHPORT` has `modify` rows for `APX900FLASHPORT` (operation-mode upgrades such as Digital Conventional to
Digital Trunking). The plain APX 900 has no Product item at all in the hierarchy.

### 2.5 Defaults (`WS1267_DEFAULTINATTR`, base model `H92UCH9PW7AN`)

| Attribute | Default |
|---|---|
| `antennasType_astro` | WHIP (STANDARD) |
| `modelSelectionHazardousLocation_astro` | N/A |
| `modelSelectionSubmersibleDeltaT_astro` | NO |
| `beltClipType_astro` | 2.0 INCH / 5.08 CM (STANDARD) |
| `manual_astro`, `advancedSystemKeyHardwareKey_astro`, `cableDataCable_astro` | NO |
| `operationModeType_astro` | DIGITAL TRUNKING (P25 PHASE I) |
| `languageLanguageType_astro` | ENGLISH |
| `multikeyType_astro` | NO MULTIKEY |
| `packingPackageType_astro` | BULK |
| `serviceType_astro` / `serviceDuration_astro` | ESSENTIAL / 7 YEAR |
| `modelSelectionHousing_astro` | BLACK |
| `baselineReleaseSW_astro` | BASELINE RELEASE |
| three documentation attributes | NO |

There is no battery default row.

### 2.6 Battery and hazardous location (`WS1267_WHITELIST`, APX900, base model ALL)

| Hazardous location | Battery options allowed |
|---|---|
| N/A | LI-ION 2100 MAH (STANDARD), 2800, 3000, 3000 (STANDARD), NO BATTERY |
| TIA4950(UL) | LI-ION 2900 MAH only |

### 2.7 Tables present for ws 1267

ACCESSORIESTOPART, AR1MATRIX, ATTRSEQUENCE, ATTRTOPART, ATTRTOPDNONFREQUENCY, BASEMODELTOCONFIG, BOMMODELS, CONFIGCLASS,
CONFIGCUSTOMERTYPE, CONFIGTOCOMMATTRMAP, CONFIGVALIDATION, CPQMODELHIERARCHY, CURRENCYCONVERSION, CUSTOMER_HEADER, DECODEMATRIX,
DEFAULTINATTR, FLAGSFORFLASHPORT, FORMULAARRAYNEW, HELPLINKS, INDUSTRYACCOUNTMAP, LOOKUPVALUES, NEWCOUNTRYREGION,
NEWCOUNTRYREGMAPPING, OUMAPPING, PDFREQMAIN, PDITEM, PDNAME, PDNONFREQ, RELSOFTANDSERVCPARTS, RTTETAREFERENCE,
SERIESMODELSMAPPING, SERVICEATOMAP, USERGROUPMAPPING, WHITELIST, WHITELIST_ASTROSYS (nothing in `src` reads the last one).

### 2.8 The sheet (APX 900 section, `APX 4500 Enhanced Configurations V6.xlsx`)

22 attributes. Mandatory: Ultimate Destination Country (US), Frequency Bands (None, 700/800, 900, VHF, UHF R1, UHF R2),
Keypad Type (**Full Keypad only**), Encryption Type (No Encryption Clear Radio, ADP Only, AES-256 SW Encryption And ADP).
Options of note: Antenna Whip (Standard) / Stubby / No Antenna; Hazardous N/A / TIA-4950 (UL); Battery LI-ION 3000 mAh
(Standard) only; Carry Type 2.0 Inch (Standard) / 2.5 Inch / No Belt Clip; Package Single / Bulk; Language English.
Open question: the sheet lists one keypad while the whitelist and the real screen offer Limited and Full.

### 2.9 Derived required set (`ASTRO25_REQUIRED_ATTRS_14_2026-10-05.json`, APX 900)

Frequency Bands, Keypad Type, Ultimate Destination Country (attrSequence R), Battery Type (attrSequence R), Encryption Type
(**blank-disallow rule, TER-gated**). EDA: encryption is `O` (optional) in attrSequence for APX 900 ("mandatory in the sheet but
not required in the data").

---------------------------------------------------------------------------------------------------------------------------

## 3. Log evidence (docker logs, aryx-api-1, 2026-10-08)

Trace ids omitted.

### 3.1 The unaffected model resolution (APX N30, after #475)
`ask.model.resolved`: `APXN30`, `deciding_step: prefer_new_radio`, alternative `APXN30FLASHPORT`. `ask.rule_scope.filtered`:
hiding rules 6,777 -> 1,323, recommendation 4,732 -> 1,878, constraint 2,804 -> 492, validation 524 -> 28, value-less hiding
2,404 -> 492.

### 3.2 Quantity holders (issue 6)
`ask.recompute.grid_diff` `GRID_QUANTITY_APPEND`: `removed: []`, `added`: `hiddenConventionalOptionsMaxQuantityAry_astro`,
`quantityPowerSupplyModulesIO_astro`, `quantityPowerAmplifierSum_astro`, `backplaneQuantityHolder_astro`,
`wallMountingQuantityHolder_astro`, `quantityAntenna1Channels_astro`, `encryptionVPSQuantity_astro` (7). `ask.recompute.pending`:
`pending_after_autofill: 0`, then `pending_count: 7`. The not-applicable guard had logged `hiddenConventionalOptionsMaxQuantityAry_astro`
as `TIER0_NOT_APPLICABLE_GUARD` on every pass.

### 3.3 Base model not derived (issues 1 and 5)
Early turns (09:07 and 09:12): `ask.base_model.not_derived`, `NOT_NARROWED_TO_ONE`, candidates `APX900`, `APX900_BOM`,
`APXFLASHPORTSERIES`, `APXFLASHPORTSERIES_BOM`; `base_models_per_candidate`: APX900 10, the others 0; `option_count` 660;
`known_attr_count` 8-9; `known_attr_match`: only `ultimateDestinationCountry` (`applied_order` 4, `base_models_with_rows` 10,
`base_models_matching` **8**, `remaining_before` 10, `remaining_after` **8**, row values BR, CA, MX, US). Band and keypad were
not among the known attributes at that point.
Run at 08:28: `modelSelectionFrequencyBands_astro = 700/800 MHZ` and `modelSelectionKeypadType_astro = LIMITED KEYPAD`, both
`TIER0_ALREADY_FILLED`, source `user`; then `NOT_NARROWED_TO_ONE`; then `modelSelectionbaseModel_astro` `FORCED_ASK_ANCHOR`.

### 3.4 Successful run (Full Keypad, 700/800 MHz, US)
`modelSelectionbaseModel_astro = H92UCH9PW7AN`, source `derived_from_known_attrs`. The configuration completed with no quantity
questions. The lists shown were the unfiltered 20 bands and 4 keypads, and keypad was asked before frequency.

### 3.5 Guessed values in the same run (issues 8 and 9)

| Attribute | Value | Source |
|---|---|---|
| `antennasType_astro` | STUBBY | `blind_pick_rule_governed`, `default_first_available` |
| `modelSelectionHazardousLocation_astro` | TIA4950(UL) | `blind_pick_rule_governed`, `default_first_available` |
| `packingPackageType_astro` | SINGLE | `blind_pick_rule_governed`, `default_first_available` |
| `batteryType_astro` | LI-ION 2900 MAH | `blind_pick_rule_governed`, `default_first_available` |
| `beltClipType_astro` | COVERT CARRY HOLSTER | `blind_pick_rule_governed`, `default_first_available` |
| `languageLanguageType_astro` | ENGLISH | `rule` |

Many encryption attributes (`encryptionEncryptionType_astro`, `addEncryption_astro`, `dataEncryption_astro`, ...) logged
`TIER0_NOT_APPLICABLE_GUARD`. `secureEncryptionType_astro` was beyond the `head -20` of the grep and was not seen.

### 3.6 Product (issue 7)
`productSelectionProduct_all = APX900FLASHPORT`, source `hint` (`COMMIT_AND_TAIL`, then `TIER0_ALREADY_FILLED`); payload value
`APX900FLASHPORT`, display `APX 900`.

### 3.7 APX 8000H (issue 11)
`ask.base_model.not_derived`: `DERIVED_CODE_NOT_AN_OPTION`; candidates `APX8000H/HXE/H-SRX` (3 base models) and `APX8000H`
(0); result `H91TGD9PW8AN`; `option_count` 46; `known_attr_match`: country (remaining 3 -> 3), `productSelectionProduct_all`
(3 -> 2), keypad (2 -> 1, applied last).

### 3.8 Environment (container `aryx-api-1`, last inspect)
On: `ARYX_CPQ_RULE_SCOPE_FILTER_ENABLED`, `ARYX_CPQ_BASE_MODEL_NARROWING_ENABLED`, `ARYX_CPQ_DERIVE_BASE_MODEL_ENABLED`,
`ARYX_CPQ_BASE_MODEL_PLACEHOLDER_GUARD_ENABLED`, `ARYX_CPQ_MODEL_SCOPED_QUESTIONS_ENABLED`, `ARYX_CPQ_MODEL_RESOLUTION_ENABLED`.
Absent: the five new flags (section 6) and `ARYX_CPQ_DEFAULTINATTR_SHAPE_ENABLED`; `ARYX_CPQ_PRODUCT_MATCH_EXACT_FIRST_ENABLED`
also absent. #478 was open and not deployed.

---------------------------------------------------------------------------------------------------------------------------

## 4. Root cause analysis

### RCA 1 and 5: the base model was not derived
1. The derivation (`derive_base_model_from_known_attrs`) applies the known answers one after another in dictionary order. A value
   that matches no remaining base model is skipped.
2. Country US is applied before the answers (`applied_order` 4). The whitelist never lists country as a target, only as a condition
   on other attributes' rows. The two 700/800 base models have country conditions BR and MX but never US, so the function reads
   them as "restricted to BR / MX" and drops them: 10 -> 8.
3. "700/800 MHZ" then matches none of the remaining 8 base models and is skipped. Keypad leaves 4. Result `NOT_NARROWED_TO_ONE`.
4. The same exclusion removes 700/800 MHz from any list built from "the base models still in play" with country alone known
   (it would have shown 4 bands, not 5).
5. The run that succeeded (3.4) shows the result depends on the order the answers reached the derivation, not on the data.
   Why that run's order differed was not verified.
Fix: apply the attributes that separate the base models first, and ignore an attribute the rows only use as a condition
(`ARYX_CPQ_DERIVE_DISCRIMINATORS_FIRST_ENABLED`). Test: with the real row shape, "country US, 700/800 MHz, Limited Keypad" left 4
base models without the flag and exactly `H92UCF9PW6AN` with it.

### RCA 2 and 3: wide lists and wrong order
The question showed every catalog option (20 bands, 4 keypads). The whitelist holds 5 and 2. The order came from the layout /
catalog order, which put keypad first; the model's own attrSequence has frequency 33, keypad 39. Fix: limit the options to the
values of the base models still in play and sort the narrowing questions by `Seq`.

### RCA 4: the first-message phrase was dropped
Hint extraction runs before the turn's model is bound (`_resolve_model_leaf` comes after it) and the Product is not yet filled on
the first message, so the model-specific rules for "700/800 MHz" (an option of several attributes) had no model. Fix: resolve the
model from the wording with the same resolver the turn uses (`known_attr_count` 8 with only country matched confirms the phrase
was missing).

### RCA 6: quantity holders after 0 pending
`resolve_pending_grid_quantities` treats a selector with no selection as "every linked option is pending a quantity" and
`append_pending_grid_quantities` runs it for every selector in the catalog. Selectors the engine had ruled out for the model
(`TIER0_NOT_APPLICABLE_GUARD`) came back as questions. `grid_diff` showed nothing removed and 7 added. Fix: seed only selectors
that were pending or already hold a selection.

### RCA 7: Product stored as `APX900FLASHPORT`
The catalog's only Product item whose label reads "APX 900" is `APX900FLASHPORT` (the flash-upgrade series; its hierarchy display
is "APX 900 FLASHport"). The plain APX 900 has no Product item. The hint step picks the only match. Model resolution still works
(it resolves `APX900` from the wording, `prefer_new_radio` over the upgrade). Lookups that fall back to the stored Product value
reach `APXFLASHPORTSERIES`, which has no whitelist rows. Not changed; see open items.

### RCA 8 and 9: guessed defaults and the battery
The `Defaultinattr` table holds the real defaults for the derived base model (2.5) but is read only with
`ARYX_CPQ_DEFAULTINATTR_SHAPE_ENABLED`, which is off. With nothing deciding them the engine took the first option. Hazardous location
guessed as `TIA4950(UL)` then forced the battery to `LI-ION 2900 MAH`, the only battery that value allows (2.6). With the default
N/A the battery set widens to five options; the table has no battery default, so the choice among them is still a guess.

### RCA 10: Encryption Type never asked
In the derived required set (used by the payload and the summary) Encryption Type is required through a blank-disallow rule gated
on the host variable `TER`; attrSequence has it optional. Ask's pending list never read the derived set. Fix: make the derived
required set "always ask, never guess" (`ARYX_CPQ_REQUIRED_SET_ASKS_ENABLED`); the guard variable counts as populated with
`ARYX_CPQ_REQUIRED_SET_GUARDS_ASSUMED_OPEN`.

### RCA 11: APX 8000H `DERIVED_CODE_NOT_AN_OPTION`
The derivation ran for an attribute whose options (46) cannot contain an H-code. The derivation runs for any attribute whose name
contains "basemodel", which includes the part-number attribute `modelSelectionBaseModelMsl_astro`. The derived code
`H91TGD9PW8AN` is a real base model of APX 8000H, HSRX and HXE. Not verified: that the 46 options are the Msl list.

---------------------------------------------------------------------------------------------------------------------------

## 5. Changes in #478

| File | Change |
|---|---|
| `src/aryx/cpq/base_model_narrowing.py` | `discriminator_option_limits`, `attr_sequence_order`, `order_ask_first`, `discriminator_values(cpq_model=...)` |
| `src/aryx/cpq/data_table/data_table_derive_base_model.py` | `single_valued_discriminators` moved here; `_in_application_order` used by `narrowed_base_models` and `explain_known_attrs` |
| `src/aryx/api/ask_turn_steps/ask_step11_build_response.py` | merge the model's values into the allowed options (`_with_model_option_limits`, `ask.options.model_limits` log) |
| `src/aryx/api/ask_turn_steps/ask_step2_catalog_hints.py` | `_model_from_wording`: the model for the hint tie-break comes from the wording |
| `src/aryx/cpq/auto_fill/auto_fill_run.py` | order the narrowing questions by `Seq` |
| `src/aryx/cpq/grid_quantity/append.py` | seed only pending selectors |
| `src/aryx/cpq/auto_fill/auto_fill_setup.py`, `engine.py`, `auto_fill_stages/governance_flags.py` | derived required set made "always ask", cached per identical fill state |
| `src/aryx/config/config_cpq_intent.py` | four new flags |
| tests | `test_cpq_base_model_narrowing_2026_10_08.py` (62), `test_cpq_derive_discriminators_first_2026_10_08.py` (6), `test_cpq_grid_quantity_pending_selectors_only_2026_10_08.py` (5), `test_cpq_required_set_asks_2026_10_08.py` (5) |

Review fixes for #474 are included: merge tests, success log, `error_class`, doc correction (a reply for a hidden option gets the
scoped re-ask from the shown list).

Test status: the four files above pass; the derive-reason (26), data-table (15, 20), grid-quantity upfront (6) and unresolved (4)
files pass. Not run: the full suite. Known failures also on `dev_oci`: `test_cpq_auto_fill_data_table_tier` (3). Four existing
grid-quantity files do not finish locally within 40 s (database-connecting).

---------------------------------------------------------------------------------------------------------------------------

## 6. Environment

Set to `true` on dev and recreate the container (a restart does not read `.env`):

```
ARYX_CPQ_BASE_MODEL_NARROWING_ENABLED=true
ARYX_CPQ_DERIVE_DISCRIMINATORS_FIRST_ENABLED=true
ARYX_CPQ_GRID_QUANTITY_PENDING_SELECTORS_ONLY_ENABLED=true
ARYX_CPQ_DEFAULTINATTR_SHAPE_ENABLED=true
ARYX_CPQ_REQUIRED_SET_ASKS_ENABLED=true
ARYX_CPQ_REQUIRED_SET_GUARDS_ASSUMED_OPEN=true
```

Already on and required: `ARYX_CPQ_DERIVE_BASE_MODEL_ENABLED`, `ARYX_CPQ_MODEL_RESOLUTION_ENABLED`, `ARYX_CPQ_RULE_SCOPE_FILTER_ENABLED`,
`ARYX_CPQ_BASE_MODEL_PLACEHOLDER_GUARD_ENABLED`, `ARYX_CPQ_MODEL_SCOPED_QUESTIONS_ENABLED`. Seen on in earlier runs, keep:
`ARYX_CPQ_ORACLE_FETCH_RULES_ORDERED_BINDS_ENABLED`, `ARYX_CPQ_MASTER_STRING_HIDE_ENABLED`, `ARYX_CPQ_NOT_APPLICABLE_GUARD_ENABLED`.
Do not set `ARYX_CPQ_PRODUCT_MATCH_EXACT_FIRST_ENABLED` (no `APX900` Product item exists) or
`ARYX_CPQ_WHITELIST_NARROW_QUESTIONS_ENABLED` (#478 covers the lists).

Verify:
```bash
docker inspect aryx-api-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E "BASE_MODEL_NARROWING|DISCRIMINATORS_FIRST|GRID_QUANTITY_PENDING|DEFAULTINATTR|REQUIRED_SET|DERIVE_BASE_MODEL|MODEL_RESOLUTION|RULE_SCOPE_FILTER|PLACEHOLDER_GUARD|MODEL_SCOPED"
```

---------------------------------------------------------------------------------------------------------------------------

## 7. Replay checklist (not yet done: #478 was not merged or deployed when this was written)

1. "I want a quote for APX 900 in the US": frequency (5 options), keypad (2 options), Encryption Type (4 options); base model derived
   with no 660-option question; antenna Whip (Standard), hazardous N/A, package Bulk, belt clip 2.0 inch; no quantity-holder questions.
2. "I want a quote for APX 900 with 700/800 MHz in the US": only the keypad is asked.
3. APX N30 and N50: now ask Encryption Type (they finished after the country before); confirm that is wanted.
4. APX 8000H: the derived base model must be `H91TGD9PW8AN` or `H91TGD9PW9AN`, never `H91TGD9PW4AN` (SRX / XE only).
5. One large model (APX 6500 or 8500): note the extra questions and the turn time.
Log checks: `ask.options.model_limits` (offered vs catalog count), `ask.base_model.derived`, `ask.fill.attribute decided` sources for the
five guessed attributes, `ask.base_model.not_derived` should not appear after both answers.

---------------------------------------------------------------------------------------------------------------------------

## 8. Open items and risks

- **Product value** `APX900FLASHPORT`: not changed. A fix changes what the customer is asked and needs its own test.
- **Keypad** : sheet lists only Full Keypad; whitelist and real screen offer Limited and Full. Decision needed (the question is limited
  to what the whitelist holds).
- **Battery default**: no table default; the 3000 mAh (Standard) in the sheet probably comes from a rule or an XML default not found yet.
- **Belt clip** `Covert Carry Holster` restriction: no rule found; the table default should replace the guess (not verified live).
- **Encryption** is mandatory in the sheet and in the derived set, optional in attrSequence: product decision recorded as "ask it".
- **`ARYX_CPQ_REQUIRED_SET_GUARDS_ASSUMED_OPEN`** is also read by the constraint-rule applier, so it changes option narrowing for guarded
  rules on every model. Splitting it from the required set would take one more flag.
- **More questions**: extra required attributes beyond frequency / keypad / country per product (upper bound): APX 900 2, 1500 Enhanced 6,
  3000 2, 4000 5, 4500 Enhanced 5, 6000 4, 6500 about 10, 8000 5, 8500 about 7, N70 7, SRX 2200 1, N30 / N50 1.
- **Cost** of the required-set derivation, measured on synthetic tables of the real size (47k attrSequence rows, 50k whitelist
  rows): `get_constraint_vals` about 10 ms, `r_flagged_names` for 4 models about 18 ms, one derivation for APX 900 about 200 ms,
  six passes about 1.2 s; 2-3 s for models with 10-13 candidates. Not measured on dev; the rule-evaluation part is not included.
  The set is reused for an identical fill state within a turn.
- **Not verified**: why the successful run (3.4) derived the base model with country known; whether `WS1267_WHITELIST_ASTROSYS` holds
  anything the engine needs; that the 46 options of the 8000H case are the Msl attribute; the live effect of every flag above.

---------------------------------------------------------------------------------------------------------------------------

## 9. Review follow-ups (PR #478: gsivasankari-giggso "approve with notes", mehmood-munir PASS with 4 Minor)

| Finding | Change |
|---|---|
| Flag dependencies not enforced | `ARYX_CPQ_REQUIRED_SET_ASKS_ENABLED` now asks nothing unless `ARYX_CPQ_REQUIRED_SET_GUARDS_ASSUMED_OPEN` is also on, and logs `ask.required_set.dependency_missing` once per process. `ARYX_CPQ_DERIVE_DISCRIMINATORS_FIRST_ENABLED` is only reached through the derivation, which already needs `ARYX_CPQ_DERIVE_BASE_MODEL_ENABLED`. Enable the flags together, in dependency order. |
| `_in_application_order` drops entries; `explain_known_attrs` omitted them | the explanation now lists an ignored attribute with `applied_order: null` and `skipped: CONDITION_ONLY_ATTRIBUTE`, so a diagnostic still sees one entry per mentioned known attribute |
| N1 `attr_sequence_order` scans the table on every call | memoised per loaded table object, model, base models and attributes (bounded, 256 entries); the memo keeps the list itself and checks identity, so a reloaded table can never reuse an old entry |
| N2 selectors only the grid flow asks would be skipped | logged: `ask.grid_quantity.selectors_skipped` (`SELECTOR_NOT_PENDING`, count and names). Not resolved: replay one catalog whose quantity grid is asked on purpose (APX NEXT, SVX) before enabling the flag there |
| N3 required-set cost unmeasured | each computation logs `ask.required_set.derived` with `duration_ms` and `required_count`; the reuse for an identical fill state is unchanged |
| Required set computed before the pass | known limit: values filled mid-pass cannot change the set within that pass. The next pass recomputes it (the cache key changes with the state). Verify with a real turn that a rule firing mid-pass does not leave a stale set |
| Double model resolution (hint step and later binding) | not changed: only extra work. A per-turn cache would remove it |
| Bundling (four flags, a moved function, docs in one PR) | accepted for a single review of one flow; the flags can be enabled and rolled back one at a time |

### Expected result for APX N30 / N50 (one place)

**Decision (owner): N30 and N50 ask only the Ultimate Destination Country. APX 900 asks Encryption Type.** This matches #475's
acceptance. It must come from the data, not from model names in code.

How the data can give it: the derived required set never contains an attribute the catalog itself filled with a default or a rule
value, and the fill stages run the catalog defaults before the "always ask" decision. With `ARYX_CPQ_DEFAULTINATTR_SHAPE_ENABLED` on, an
encryption default in `WS1267_DEFAULTINATTR` for the N30 / N50 base models keeps them silent, while APX 900 (no encryption row for
`H92UCH9PW7AN`, all rows seen) asks it.

**Not verified:** that those N30 / N50 rows exist (query: `SELECT BASEMODEL, ATTR1, VAL1 FROM WS1267_DEFAULTINATTR WHERE ATTR1 =
'secureEncryptionType_astro'`). If they do not, the engine would ask them Encryption Type and the cause of the real CPQ's silence is
elsewhere (for example the conditions of the blank-disallow rule); a per-model switch is a last resort. Replay N30 / N50 with all flags
on before relying on it.

### N30 / N50 vs APX 900: what the data says about Encryption Type (query results and export)

`WS1267_DEFAULTINATTR` rows with `ATTR1 = 'secureEncryptionType_astro'`: only `T05KSS9PW1AN` and `T05QSS9PW1AN` (value
`AES ENCRYPTION`). **No N30, N50 or APX 900 base model has an encryption default**, so the Defaultinattr flag does not keep N30 / N50
silent. `WS1267_BASEMODELTOCONFIG`: `APXN30` = H15KDF9PW6AN, H15UCF9PW6AN, H15XDF9PW6AN; `APXN50` = H25KDF9PW6AN, H25UCF9PW6AN,
H25XDF9PW6AN (plus FLASHPORT part numbers T99xx).

From `ASTRO25_REQUIRED_ATTRS_14_2026-10-05.json` (all three products, layout `portable`, coverage 1.0): the same validation rule,
"Restrict blank value for Encryption Type for US or FED customers (Portable)" [condition true], makes Encryption Type required for
APX 900, N30 and N50. N50 additionally has a script that may fill the security bundle ("Set Recommendation Selection for the Security
Bundles"); N30 has none.

From EDA section 10.4: for APX 900 and N50 the encryption rule is TER-gated only (dormant without the host's TER input); for N30 there is
also "Restrict Blank Value for Encryption Type for APXN30 PR/VI", which fires without TER. EDA section 11 (red set without TER) does
not list Encryption Type for APX 900; the sheet lists it as mandatory (with TER, as in production).

Conclusion: the rules and tables treat the three products alike. "APX 900 asks Encryption Type, N30 / N50 ask only the country" cannot
be derived from this data. Open question for the owner: is the N30 / N50 observation from a real CPQ run with TER populated, or from
a run without it? If both products behave differently in production, the difference lives in something not found yet. Options:
(A) leave `ARYX_CPQ_REQUIRED_SET_ASKS_ENABLED` off (APX 900 does not ask encryption either); (B) turn it on and accept the question for
N30 / N50 (consistent with the rules); (C) a per-model list in configuration (cpq models allowed to use it), no model name in code.

### RCA: why the real UI shows Encryption Type for APX 900 and not for N30 / N50

Sources in this repo: `CPQ_REQUIRED_INPUT_DERIVATION_PLAN_2026_10_05.md` (screenshot ground truth and the rule analysis),
`CONFIG_DATA_REQUIRED_FIELDS_FINDINGS_AND_CODE_CHANGES_2026-10-05.md`, `CONFIG_DATA_ALL_PRODUCTS_US_2026-10-06.md`,
`ASTRO25_APX_PRODUCT_EDA_2026-10-03.md` section 10.4. Nothing below was run live.

1. **The screenshots are at different states.** Ground truth used for the derivation: APX 900 shows "Country, Frequency Bands, Keypad Type,
   Encryption Type" (taken after the band and keypad were chosen, so the base model was resolved); APX N30 shows "Country only" (the
   initial state). The derivation plan says so itself: "APX N30 Encryption Type in pass 2, a state later than its screenshot".
2. **Encryption Type is state dependent, not product dependent.** It is `O` in attrSequence. It is required by the blank-disallow rule
   "Restrict blank value for Encryption Type for US or FED customers (Portable)", whose condition needs **the base model resolved AND
   country US** (or Federal plus the FCC feature). The rule is also gated on the host variable `TER`
   (`if(sessionVariable_TER <> "")`); the production screenshots show the TER-gated message "Please make at least one selection from
   Encryption Type", so TER is populated in production.
3. **Same rule for all three products.** The derived sets list the rule as true for APX 900, N30 and N50 alike; N30 also has a rule
   for PR / VI that fires without TER. N30 / N50 have a package-bundle default (`softwareBundlesBundleType_astro = STANDARD BUNDLE`) that fires
   a recommendation chain and fills Operation Type; it restricts one encryption value ("ADP ONLY <- packageTypeBundles") but does not fill
   Encryption Type.
4. **So the difference is when the screenshot was taken.** APX 900 needs two answers before its base model resolves, so the red field was
   captured; N30's initial screen shows only the country, and the prototype predicts Encryption Type after country US and a resolved base
   model. #475's acceptance ("nothing asked after the country") was compared with that initial-state screenshot, not with a screen after
   the country was chosen.

**Not verified:** a real N30 / N50 screen **after** choosing United States. That one screenshot decides it: if Encryption Type goes red,
the flag should be global (option B) and N30 / N50 asking it is correct; if it stays absent, something outside the rules above applies and
needs a new RCA (a per-model list is a last resort).


### PR #482: blind picks are re-derived when the context changes

A value guessed early in a turn with `blind_pick_*` sources (`blind_pick_rule_governed`, `blind_pick_governed`) is now re-derived on a
later pass when the fill signature changed, as `default_first_available` values already were. **Customer-visible effect:** a guessed value
shown in an earlier turn can change in a later turn when new context arrives (for example the base model resolving): that is the fix, and the
same kind of change as the existing `default_first_available` case; a customer's own answer (source `user`) never changes.

Added work and how to measure it: each carried-over `blind_pick_*` value is re-derived once on the first pass of a turn (the signature dict
starts empty) and afterwards only when the signature changes. The log reason is `BLIND_PICK_REDERIVE` (the old reason
`DEFAULT_FIRST_AVAILABLE_REDERIVE` is unchanged), so for one turn:
`docker logs aryx-api-1 --since 10m 2>&1 | grep -c BLIND_PICK_REDERIVE`, next to `ask.rules_loop.timing`.
