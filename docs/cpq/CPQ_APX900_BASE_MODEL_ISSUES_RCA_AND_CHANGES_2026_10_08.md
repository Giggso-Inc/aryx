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

## Fix plan 2026-10-08 (RCA 1-3 of the "900 MHz" run) and final environment

Run: "APX 900 in the US", answer 900 MHz: the quote completed with Keypad = Full and Base Model `H92WCH9PW7AN`; the summary held 5 guessed attributes
and no Encryption Type.

1. **Silent keypad.** The engine's country filter drops `H92UCF9PW6AN` and `H92WCF9PW6AN` (no US row among OTHER attributes' rows), so 900 MHz leaves one
   base model and the keypad is forward-filled. The real UI keys band and keypad by region (NA rows exist for all 10 base models) and offers Limited and
   Full. Fix: `ARYX_CPQ_DERIVE_DISCRIMINATORS_FIRST_ENABLED=true` (code from #478, config only).
2. **Missing attributes.** `WS1267_DEFAULTINATTR` holds 18 defaults for `H92WCH9PW7AN` (no `languageLanguageType_astro` row; an extra
   `antennasFrequency_astro` = 900 MHZ); only 5 attributes showed, all blind picks. Fix: `ARYX_CPQ_DEFAULTINATTR_SHAPE_ENABLED=true` plus PR #482 (a blind pick
   yields to the table default once the base model is known). Battery has no default row; Language has none for WCH.
3. **Encryption Type** (mandatory in the sheet, O in attrSequence, required by a TER-gated blank-disallow rule). Fix: the asks flag takes only
   rule-required attributes (not attrSequence R), with its own guard setting `ARYX_CPQ_REQUIRED_SET_RULE_GUARDS_ASSUMED_OPEN` that only the required set
   reads: the constraint-rule applier keeps today's behaviour on every model (the older `ARYX_CPQ_REQUIRED_SET_GUARDS_ASSUMED_OPEN` also changes it).

Environment for dev (recreate the container): 
`ARYX_CPQ_DERIVE_DISCRIMINATORS_FIRST_ENABLED=true`, `ARYX_CPQ_DEFAULTINATTR_SHAPE_ENABLED=true`, `ARYX_CPQ_REQUIRED_SET_ASKS_ENABLED=true`,
`ARYX_CPQ_REQUIRED_SET_RULE_GUARDS_ASSUMED_OPEN=true`; keep the prerequisites listed above. Do NOT set `ARYX_CPQ_REQUIRED_SET_GUARDS_ASSUMED_OPEN`.

Replay (one step at a time): (A) answer 900 MHz: the keypad is asked with 2 options; Limited + 700/800 derives `H92UCF9PW6AN`.
(B) the summary lists the 18 defaults (antenna Whip, hazardous N/A, carry 2.0 inch, package Bulk). (C) after band and keypad, Encryption Type is asked
with 4 options and no FCC Trigger question appears. Expected side effect: APX N30 / N50 also ask Encryption Type (same rule); confirm with one real
screenshot after the country is chosen.

### Review follow-ups on the required-set ask (2026-10-08)

- Hiding rules are applied to the ask set only once the base model is known (master-string hide rules say "hide" while it is blank), without
  writing rule-trace rows (`rule_trace_state.untraced`). The `cpq_perf: apply_hiding_rules` info line is still logged, and the call runs once per
  distinct fill state (cached for the turn). Script-backed hide rules need the BML evaluator: when none is passed they leave the attribute visible,
  so it is still asked (safe direction).
- Two guard settings can satisfy the asks flag: `ARYX_CPQ_REQUIRED_SET_RULE_GUARDS_ASSUMED_OPEN` (use this one) and the older
  `ARYX_CPQ_REQUIRED_SET_GUARDS_ASSUMED_OPEN` (also changes the constraint-rule applier; do not set). The WARN reason code is now
  `REQUIRED_SET_RULE_GUARDS_ASSUMED_OPEN_OFF`. Retiring the old flag is a separate change.

### Fix B2: a Defaultinattr default breaks a tie the Whitelist leaves (2026-10-08)

The defaults flag alone does not apply defaults to attributes the Whitelist covers: with `ARYX_CPQ_DEFAULTINATTR_SHAPE_ENABLED` on, a Whitelist
that leaves 2+ legal values returns before the table is consulted ([conflicts.py], comment "a Defaultinattr default must not override it").
Dev log (30 minutes, every pass): `ask.datatable.lookup` `AMBIGUOUS_DISCARDED` for `antennasType_astro`, `beltClipType_astro`,
`packingPackageType_astro` and, on most passes, `modelSelectionHazardousLocation_astro`; hazardous showed `SINGLE_LEGAL_VALUE` on others, because a
guessed battery (2900 mAh) forces TIA-4950 (UL) through the Whitelist.

Change: new flag `ARYX_CPQ_DEFAULTINATTR_RESOLVES_AMBIGUITY_ENABLED` (off by default; needs the defaults flag). When the Whitelist leaves 2+ legal values
and the resolved base model's Defaultinattr default is one of them (case-insensitive) and a real option, that default is taken (log reason
`DEFAULTINATTR_AMONG_LEGAL`). It never overrides the Whitelist. A default outside the legal values, a single legal value, an empty legal set and an
attribute without Whitelist rows behave as before. Needs the base model known and PR #482 (an early guess is re-opened when the context changes).

Expected for APX 900 / `H92WCH9PW7AN`: antenna Whip (Standard), hazardous N/A, carry 2.0 inch / 5.08 cm (Standard), package Bulk. Battery has no default
row: it stays a guess among the five N/A allows (2900 mAh is no longer legal). Language has no row for WCH.

Environment: `ARYX_CPQ_DEFAULTINATTR_SHAPE_ENABLED=true` and `ARYX_CPQ_DEFAULTINATTR_RESOLVES_AMBIGUITY_ENABLED=true`. Replay: the summary shows the four
defaults above; `grep DEFAULTINATTR_AMONG_LEGAL` lists the attributes resolved this way. Risks: reaches every model and attribute that has a table default
and 2+ Whitelist values; fills silently; turn time not measured.


### PR #482: blind picks are re-derived when the context changes

A value guessed early in a turn with `blind_pick_*` sources (`blind_pick_rule_governed`, `blind_pick_governed`) is now re-derived on a
later pass when the fill signature changed, as `default_first_available` values already were. **Customer-visible effect:** a guessed value
shown in an earlier turn can change in a later turn when new context arrives (for example the base model resolving): that is the fix, and the
same kind of change as the existing `default_first_available` case; a customer's own answer (source `user`) never changes.

Added work and how to measure it: each carried-over `blind_pick_*` value is re-derived once on the first pass of a turn (the signature dict
starts empty) and afterwards only when the signature changes. The log reason is `BLIND_PICK_REDERIVE` (the old reason
`DEFAULT_FIRST_AVAILABLE_REDERIVE` is unchanged), so for one turn:
`docker logs aryx-api-1 --since 10m 2>&1 | grep -c BLIND_PICK_REDERIVE`, next to `ask.rules_loop.timing`.

### Optional attributes with no basis are left unanswered (2026-10-09)

APX 3000 / US on dev: Mission Critical Wireless Accessory Bundle is optional (`O` in attrSequence), has no Defaultinattr default and the Whitelist leaves 3
values (`AMBIGUOUS_DISCARDED`), yet it was filled "Accessory Bundle Pack 1" by `default_first_available`, then re-sourced `blind_pick_governed` /
`blind_pick_rule_governed`, and went into the BOM. The real screen offers "None" first. (Surveillance Package Beige and the Carry Type default are
`defaultinattr`-sourced and are not changed here.)

Change: new flag `ARYX_CPQ_NO_BLIND_FILL_OPTIONAL_ENABLED` (off by default). A single-select that is not catalog-required, not a decision / forced-ask /
derived-required attribute and that no earlier stage resolved is left open (log `OPTIONAL_NO_BASIS`) by the blind stages
(`tier6_single_b` first-by-order branches, `ask_or_pending` before `try_dt_governed_blind` / `try_rule_governed_blind`). The menu's sole explicit opt-out
option is still taken. Not changed: multi-selects, required attributes, anything with a hint, recommendation, Data Table or default.

Risk: a rule cascade that relied on the blind value stays open; the summary carries fewer filled values; reaches every model; turn time not measured. Replay
APX 3000: the accessory bundle is absent from the summary and the log shows `OPTIONAL_NO_BASIS`.

### Restrict.../Hide... declarative lists are the values taken away (2026-10-09)

APX 4000 / US on dev: the band question offered 700/800, VHF, UHF R1 and UHF R2 (log `ask.options.model_limits`, `offered_count 4`) and left out 900 MHz, the only band
the real screen offers (and the sheet's APX 4000 block). Cause: the declarative action of "Restrict Frequency Band except 900MHz" (`set_type -1`, `~VHF~700/800
MHZ~UHF R1~UHF R2~8/900 MHZ`) is loaded as an allow-list (`value_rules_bucket.py` -> `ConstraintRule(allowed_values)`, mode empty). The rule lists the values
it takes away. The same loader reading also narrows an attribute to the listed values whenever any Restrict rule's condition holds (e.g. "Restrict Flash Model
Numbers ... | M22VRS9PW1CN" would force that base model).

Audit (ws 1267, dev Oracle): `set_type -1` carries `action_type` 1 (1,464 actions) and 2 (2,947); the type does not separate the readings (Restrict 1,862 on type 2,
605 on type 1; Constrain 420 / 374). 183 Restrict actions (167 rules) and 13 Hide actions carry a value list; 178 Constrain actions (155 rules) do too. Of 40
sampled Restrict/Hide rules about 33 are clear remove-lists, none an allow-list, about 7 are quantity or number limits. "Constrain..." rules go both ways (a
live-confirmed one, "Constrain for APXNEXTSINGLE...", is an allow-list), so they are not touched.

Change: new flag `ARYX_CPQ_RESTRICT_HIDE_LISTS_ARE_REMOVE_ENABLED` (off by default). A rule whose name starts with Restrict or Hide gets `ConstraintRule.remove_list`;
`effective_allowed` then returns the target's options minus the listed values (case/space-insensitive). The old allow-list reading is kept when no listed value is a
real option (quantity limits, numbers, free-text attributes) or when nothing would be left (a list must not empty the attribute and trigger the empty-intersection
fallback). Not changed: Constrain/Constraint rules, script-backed rules, `cpq/validation` (the offline reference oracle).

Risk: reads about 196 declarative actions the other way for every model, so option lists change widely; the reading rests on names and values, not on Oracle's
definition. Replay: APX 4000 offers only 900 MHz; check other models whose Restrict rules fire. Turn time not measured.

### Hidden master strings count as non-blank for the required set (2026-10-09)

With `ARYX_CPQ_CONSTRAINT_MODE_ENABLED` on, `ask.required_set.derived` still never listed Encryption Type. Inputs of "Restrict blank value for Encryption Type for US or FED
customers (Portable)" on ws 1267 (operator `3` = `<>`): base model not blank; `hiddenConstraintMasterString_astro` not blank; country US or (Customer Type FEDERAL and a FED FCC
trigger feature); a model from a list (aPX900, aPX3000, aPX4000, aPX1000, aPX6000/5000, sRX2200, aPXNext; aPX8000Series only without CBP TRIGGER; aPXN30/aPXN50 only without
ESSENTIAL CORE BUNDLE); product not APX4000XH. The N30/N50 clause is why a real N30 with Essential Core Bundle shows no Encryption Type. Three things stop it in Aryx:
(1) the OR between country and Customer Type needs `ARYX_CPQ_CONDITION_EXPRESSION_ENABLED` (F3); (2) nothing in the engine fills `hiddenConstraintMasterString_astro`, so its "not blank"
input is never true; (3) `_bm_model_variable_name` must be in the quote (not checked).

Hidden attributes used as an "is not blank" rule input (ws 1267): master strings `hiddenConstraintMasterString_astro` (74 rules), `...ForBaseModel_astro` (37), `defaultAttrValuesMasterString_astro` (10),
`hiddenMasterStringForRelatedServices_astro`, `hiddenAccesoriesMasterString_astro` (2 each), `hiddenMasterStringForAstroMobile_astro`, `hiddenSeriesModelsMasterString_all` (1 each); and not master
strings: `pdKey_astro` (24), `modelSelectionRegion_astro` (14), `configAction_all` (2), and four with 1 rule each (incl. `customerUIN`).

Change: new flag `ARYX_CPQ_REQUIRED_SET_MASTER_STRING_PRESENT_ENABLED` (off by default; required-set derivation only). A hidden, option-less attribute whose name contains "MasterString" that the quote
does not fill is given a non-blank stand-in when a blank-disallow or message-only rule tests it. The rule's other inputs still decide, so the model, bundle and product exclusions above are untouched.
pdKey, Region, Customer UIN and attributes with options are never assumed. Needs `ARYX_CPQ_CONSTRAINT_MODE_ENABLED`, `ARYX_CPQ_REQUIRED_SET_ASKS_ENABLED`, `ARYX_CPQ_REQUIRED_SET_RULE_GUARDS_ASSUMED_OPEN` and, for the
country-or-FED OR, `ARYX_CPQ_CONDITION_EXPRESSION_ENABLED`.

Risk: Encryption Type (and any other rule gated on a master string) can be asked where real CPQ's master string would be blank (a base model with no rows); the match is by name, so another catalog that names
its master strings differently is unaffected. F3 changes how every multi-input rule is evaluated. Replay APX 900 / 3000 / 4000 / 8500: `ask.required_set.derived` lists `secureEncryptionType_astro`; N30 with
Essential Core Bundle does not.

### The ask-set hide check counts host-supplied context as blank (2026-10-09)

With `ARYX_CPQ_REQUIRED_SET_ASKS_ENABLED` and the guard flag on, `ask.required_set.derived` listed one attribute on SRX 2200, APX 8500 and APX 900
(`required_count 1`, `requireForRadioFEDFCCTriggerSS_astro`) and "Do You Require Radio FCC Trigger?" was asked first. No real screen (APX 3000, 4000, 8500) shows
it. Rules on ws 1267: about 14 script-backed `Constrain "None" for ...` / `Constraint Radio FED FCC Trigger for US customer` (`set_type -1`, blank-disallow once
`cpq_constraint_mode_enabled` loads them) require it from the country alone; "Hide ... on Non FED Customer", "Associate Recommendation Rule: Hide ... when <> FEDERAL"
and per-product hides remove it, but need Customer Type, which a quote does not carry (the host supplies it). `evaluate_declarative_conditions` treats an unfilled
attribute as unknown, so the hide never fires; the real screen counts it blank.

Change: new flag `ARYX_CPQ_ASK_HIDE_ASSUMES_BLANK_HOST_CONTEXT_ENABLED` (off by default; only affects the hide check inside the required-set ask). A second pass runs the
DECLARATIVE hide rules (never script-backed or master-string ones) with every free-text attribute that has no menu options and is absent from the quote counted as blank,
and it runs before the base model is known too. The existing pass (all rules, real answers, base model known) is unchanged. Attributes with options or answers are never
blanked.

Risk: a Federal customer's quote skips a question the real screen asks (keep the flag off, or supply Customer Type, for Federal quotes); another declarative hide that
matches on a blank free-text attribute can now hide an attribute earlier. Replay: the FCC question is not asked on SRX 2200 / APX 8500 / APX 900; `required_vns` no
longer lists it.


### Diagnostic logs for the dev findings of 2026-10-09

Two findings from the dev log (541 MB, 22:34 to 03:33): Encryption Type is hidden by "Hide Secure Attributes If No Values Available (Mobile)" / "Hide Encryption Type Attribute If No
Values Available (Portable)" decided from the computed master string (`hide_decided`, 88 records), and N50's base model becomes `TT2592A` / `T8343A`, written by a rule (`ask.base_model.write`, source
`rule`, site `resync_stale_recommendations`). Logging only; no result changes. Read them with:

| Question | Log line (DEBUG unless noted) | Fields |
|---|---|---|
| Was the hide of Encryption Type decided on a master string built for the right model? | `ask.rules_loop.master_context` (reason `DECIDED_MASTER_STRING_CONTEXT`) | `rule_name`, `attr`, `master_var`, `cpq_model`, `base_models`, `master_names`, `target_in_master`, `names_sample`, `live_writers` |
| Why is an attribute (not) in the asked set? | `ask.required_set.diagnostic` | `rule_found`, `kept`, `dropped` (attribute -> `not_in_attribute_list` / `catalog_hidden` / `hide_in_trans` / `hidden_by_rule` / `not_in_layout` / `catalog_filled` / `no_legal_value` / `script_filled_quantity`), `blank_disallow_loaded`, `blank_disallow_condition_fired`, `blank_disallow_guard_closed`, `validation_loaded`, `validation_fired`, `assumed_master_strings` |
| What did the hide check remove from the asked set? | `ask.required_set.hidden` | `hidden_count`, `hidden_vns`, `base_known`, `blank_host`, `rules_total` |
| Did the hide check fail? | `ask.required_set.hide_check_failed` (WARN) | `error_class`, `error` |
| Which rule wrote a base-model value, and does it look like a base model? | `ask.base_model.rule_value` (WARN `ARYX_ASK_BASE_MODEL_RULE_SHAPE` when the shape differs from the value it replaces) | `rule_name`, `rule_ref_id`, `recommended_state`, `current_state`, `shape_recommended`, `shape_current`, `condition_attr_ids`, `condition_values` |

Error codes (WARN, always on; the repo has no separate error-code catalog, so they are listed here and in the code): `ARYX_ASK_REQUIRED_SET_HIDE_CHECK_FAILED` (P3, the required-set hide check raised; nothing extra was
hidden, read `error_class` / `error`) and `ARYX_ASK_BASE_MODEL_RULE_SHAPE` (P3, a recommendation rule wrote a base-model value whose letter/digit pattern differs from the value it replaced, read `rule_name`).

```bash
docker logs aryx-api-1 2>&1 | grep -E "ask.rules_loop.master_context|ask.required_set.diagnostic|ask.required_set.hidden|ask.base_model.rule_value" | cut -c1-900
```

How to read the Encryption Type case: `master_context` with `target_in_master: false` and a `cpq_model` / `base_models` that is not the quote's model means the master string was built for the wrong scope (for example a Mobile rule
evaluated for a portable model); `target_in_master: true` with `hide` would be a different problem. `ask.required_set.diagnostic` shows whether the blank-disallow rule fired (`blank_disallow_condition_fired`) and then why the
attribute was dropped (`hidden_by_rule` is the master-string hide).


### The completeness check skips attributes no model of the product lists, before the base model is known (2026-10-09)

ASTRO model testing (ws 1267): APX 8000 and 6000 answer "This configuration is missing required data: Is FLASHcode Available?, Quantity, Power Adapter" on the first message; APX 4500 / 1500 / 6500
Enhanced after the first answers. The message comes from `ask_stale_constraint_reask.py` (`find_missing_required_fields`), over the attribute list `_applicable_attrs` returns. The three attributes
are catalog-required but belong to other flows (flash upgrade, ASTRO systems): no attrSequence row of these models lists them. `cpq_model_scoped_questions_enabled` (#475) drops such attributes
only once the base model is known; with the base model empty it changes nothing, and on the first message of APX 8000 / 6000 nothing has been asked, so it never is.

Change: new flag `ARYX_CPQ_COMPLETENESS_SCOPE_BY_PRODUCT_ENABLED` (off by default; completeness check only). While the base model is empty, an attribute that no attrSequence row of any of the
product's candidate models lists (at any base model) is left out of the check. Kept: the decision anchors, attributes holding a customer or engine-context value, everything when the product has
no sequence rows. Once the base model is known the existing base-model scoping decides, as before. No attribute or model name is involved.

Not changed: the questions themselves, the BOM gate at confirm (`bom_gate.find_missing_required_fields` still sees the full list), the `*FLASHPORT` product value in the payload, N50's base model,
APX 4000's Product question. APX 8000 / 6000 have no pending questions on turn 1, so with the three attributes out they can go straight to "Configuration complete" instead of stopping; that needs a
separate look.

Risk: a required attribute no sequence row lists but the real screen does show (a catalog gap) would no longer block completion at the proactive check; the confirm gate is unchanged. Replay APX 8000 / 6000 /
4500 / 6500: the "missing required data" message no longer lists the flash-code attributes. Turn time not measured.


### Where an auto_fill pass spends its time (2026-10-09)

Dev log (541 MB, 22:34 to 03:33, one container run, 18 quote sessions): a turn takes 6 to 7.5 minutes for APX 900 (449, 364, 385, 368 s) and can pass 15 minutes. The time is in `auto_fill`: 112 passes, 45 of them over
two minutes, the slowest 245 s; the post-loop `auto_fill` about 120 s; `mandatory_tier_c_vns` 11 to 148 s (nine calls, the last two the slowest). Not the cause: `apply_hiding_rules` (about 1.3 s per pass) and the Oracle statements
(27,638 in total; `SELECT aryx_entity` 294 s over 1,564 calls). A turn runs 1,000 to 3,000 attribute decisions in 2 to 4 passes. `cpq_perf: auto_fill took` times the whole pass, so the log could not say which stage or attribute is slow.

Logging only: one `cpq_perf: auto_fill stages` INFO line per `auto_fill` call (the loop pass and the post-loop one), written by `run_auto_fill` and filled by `resolve_one_attr`:

`cpq_perf: auto_fill stages pass=<n> total=<s> attrs=<n> in_attrs=<s> outside_attrs=<s> trace_overhead=<s> stages=[stage_fn=<seconds>/<calls> ...] slowest_attrs=[variable=<s> ...]`

- `in_attrs`: seconds inside the per-attribute loop; `outside_attrs`: setup (context and scope build) plus the post-passes after the loop; `trace_overhead`: attribute time minus the time of its stages, which is the DEBUG stage-trail logging.
- `stages`: the eight slowest stage functions with total seconds and number of calls; `slowest_attrs`: the six slowest attributes.

```bash
docker logs aryx-api-1 2>&1 | grep "cpq_perf: auto_fill stages" | cut -c1-900
```

How to read it: a large `outside_attrs` points at the setup or the post-passes (for example the data-table loads, 13 to 23 s per fresh scan); a large `trace_overhead` means the DEBUG logging itself is slow, so lowering the log level would speed the turn up;
one dominant stage (for example `stage_options` or `stage_default_value`) or a few dominant attributes name the code to fix.

### Why Encryption Type's blank-disallow rule does not fire (2026-10-09)

First replay with #494 on dev (APX 900, 05:35 UTC): `ask.required_set.hidden` shows `base_known true`, `blank_host true`, `hidden_count 0`; `ask.required_set.diagnostic` shows `attr_count 25`, `blank_disallow_loaded 19`,
`blank_disallow_condition_fired 1` (the FCC trigger), `assumed_master_strings 0`, `dropped {}`. So the required set is derived over only 25 attributes (the visible, model-listed ones). A rule input on an attribute that is not
among them (Customer Type, the hidden constraint master string, the model variable) can never be read, and the two flags written for it have nothing to act on: the blank-host pass finds no attribute to blank, and `assumed_master_strings` is 0.
This is the explanation the data fits; it is not proven until the new field below shows `unmapped` on those inputs.

Logging only: `ask.required_set.diagnostic` now carries `unfired_blank_disallow`, up to 20 entries `{rule, target, script_condition, conds: [[attribute, operator, value, state]]}` for every blank-disallow rule that did not fire,
where `state` is `unmapped` (the attribute is not in the list the check was given), `true`, `false` or `unknown`.

```bash
docker logs aryx-api-1 --since 20m 2>&1 | grep "ask.required_set.diagnostic" | tail -1 | cut -c1-6000
```

Reading it: for the Encryption Type rules (`target secureEncryptionType_astro`), `unmapped` on Customer Type / the master string / the model variable confirms the cause (the fix is to resolve rule conditions against the full attribute list while
keeping the visible list for targets); `false` on country or the base model means the rule does not apply to this model (for example the N30/N50 Essential Core Bundle clause); `unknown` on an attribute that is in the list means its value
is missing.
