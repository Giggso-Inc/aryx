# CPQ Raw-XML Rule Trace — APX NEXT Enhanced / 5G / US Scenario

Source export: `C:\Users\ADMIN\Downloads\APXNext_CnofigData.xml` (28.5MB, 48,517 lines, company_id 4118171, catalog `aPXNext_BOM`).

Scenario: Country=US, `hWVersion_astro` = `NEXT ENHANCED LTE PLUS 5G` ("APX NEXT (4G LTE+5G)"), `productSelectionProduct_all` = `APX NEXT ENHANCED` ("APX NEXT Enhanced"). Native UI shows "Configuration complete" immediately after Product, no further questions.

## Summary Table

| Attribute | Verdict | Why (one line) |
|---|---|---|
| `hWVersion_astro` | **CORRECT** | Purely user-selected; the only rules that could default it (`Default hardware version for APX Next`, id 18131370853) are `status=3` (INACTIVE) in this export. |
| `productSelectionProduct_all` | **CORRECT** | User-selected from an active constrained list. Rule `Restrict APX Next Product Selection based on HW Version selection` (id 17691443811, status=1) narrows options to exactly `APX NEXT ENHANCED` / `APX NEXT XE 4G LTE PLUS 5G` when `hWVersion_astro=="NEXT ENHANCED LTE PLUS 5G"`. The rule that would have *auto-defaulted* it (`Default APX Next ENhanced based on HW version`, id 17691442943) is `status=3` INACTIVE. |
| `relatedServicesType_astro` | **NEEDS MORE DATA** | Active rule `Restrict Related Service Type` (id 18654807132) computes the allowed list from data table `relSoftAndServcParts` filtered by `cpqModel=productSelectionProduct_all`. Whether that table has exactly one row (`serviceType=INSTALLATION`) for `APX NEXT ENHANCED` was not confirmed — export contains no literal `INSTALLATION` row match found for this specific model in the time available. |
| `accessoriesSolutionSet_astro` | **NEEDS MORE DATA** | Active rule `Constraint solution set based on product` (id 18131370887) computes the allowed list from `Oracle_BomItemMap`/`Oracle_BomItemDef` (`ItemType='Accessories'`, `ConfigAttrValue LIKE %APX NEXT ENHANCED%`). The generic "default if only one value available" rule (id 17691443441) does **not** target this attribute's id (17691442430) at all — no auto-select rule confirmed; value would only be correct if the BOM table happens to have a single `ItemCategory` = `ANTENNAS CABLE OTHER` row for this product, which was not verified. |
| `carrierSelectionMultiSelect_astro` | **INCORRECT** | Every rule found that sets a value into this attribute (`Force VERIZON carrier selection` id 18654807104, `Default verizon for Dual sim` id 18654807102) is gated on a specific `customerUIN=H55TGT9PW8BN` + a dual-SIM flag — none apply to a generic US/Enhanced/5G scenario, and both would force **VERIZON**, not ATT/FIRSTNET. No rule anywhere in the 20 rule-hits for this attribute's id (18302531460) computes/defaults ATT/FIRSTNET. This matches the second screenshot's evidence that Wireless Carrier is a genuine unanswered required field for this product family — it should not appear pre-resolved in `configData` at all. |
| `additionalSystemEnhancementFeatureType_astro` | **INCORRECT** | The only rule found that sets `DISABLE CLOUD SERVICES` (`Default Disable Cloud Services for customerUIN 1070001185 for APX Next intl fed israel for Custom`, id 17691442961) requires `productSelectionProduct_all=="APX NEXT INTL FED"` AND country=`IL` AND `customerUIN=="1070001185"` AND package type=`CUSTOM`. None of these match the US/`APX NEXT ENHANCED` scenario. No other active rule targeting this attribute's id (17691442162) defaults it for this context. |

## Per-Attribute Detail

### 1. hWVersion_astro (attribute id `17691442282`)
- `BmConfigAttr`: name "Hardware Version", `display_type=3` (dropdown), `required=0`, `status=1`.
- 16 rule blocks reference this id, all as a **condition input**, not as an action target, except two INACTIVE rules:
  - `Default hardware version for APX Next` (rule id 18131370853, `status=3`)
  - No active rule sets this attribute's value.
- **Verdict: CORRECT** — value is exactly the user's selection, unmodified by any active rule.

### 2. productSelectionProduct_all (attribute id `39427019`)
- Rule `Default APX Next ENhanced based on HW version` (rule id 17691442943, **status=3 INACTIVE**):
  ```
  condition_expression: 1
  input: attribute_id=17691442282 (hWVersion_astro) operator=4 value1="NEXT ENHANCED LTE PLUS 5G"
  action script (function 17691441583):
    returnVal = "";
    if(hWVersion_astro == "NEXT ENHANCED LTE PLUS 5G"){
        returnVal = "APX NEXT ENHANCED";
    }
    return returnVal;
  ```
  This rule *would* auto-set the exact JSON value, but it is inactive, so it does not fire.
- Rule `Restrict APX Next Product Selection based on HW Version selection` (rule id 17691443811, **status=1 ACTIVE**, `rule_type=2` constraint):
  ```
  condition_expression: 1 AND (2 OR 3 OR 4)
  action script (function 17691442051):
    returnVal = "";
    if( (hWVersion_astro=="NEXT ENHANCED LTE PLUS 5G")){
        returnVal = "APX NEXT ENHANCED|^|APX NEXT XE 4G LTE PLUS 5G";
    }
    else{ ... other product list ... }
    return returnVal;
  ```
  This narrows the selectable list to two values, of which the user picked `APX NEXT ENHANCED`.
- **Verdict: CORRECT.**

### 3. relatedServicesType_astro (attribute id `17691442394`)
- Rule `Restrict Related Service Type` (rule id 18654807132, status=1, ACTIVE) — action targets this exact attribute id:
  ```
  script (function 18654805897):
    selModel = upper(_bm_model_variable_name);
    if(productSelectionProduct_all<>""...) selModel = productSelectionProduct_all;
    DataTableRecordsSets = bmql("SELECT DISTINCT serviceType FROM relSoftAndServcParts WHERE cpqModel=$selModel");
    for data in DataTableRecordsSets{ returnVal = returnVal + get(data,"serviceType") + "|^|"; }
    return returnVal;
  ```
- Separately, `Populate Related Services And Software Array` (rule id 17691442855, status=1) sets *other* related-service sub-attributes (ids 17691442510/522/512/514/516/450/446) from a pre-built hidden master string (`hiddenMasterStringForRelatedServices_astro`), not the Type selector itself.
- **Verdict: NEEDS MORE DATA.** The mechanism is real (data-table driven distinct list), but confirming the value resolves to exactly `INSTALLATION` requires reading the `relSoftAndServcParts` table rows keyed on `cpqModel="APX NEXT ENHANCED"`, which was not completed in this pass.

### 4. accessoriesSolutionSet_astro (attribute id `17691442430`)
- Rule `Constraint solution set based on product` (rule id 18131370887, status=1, ACTIVE):
  ```
  script (function 18131369748):
    cpqModel = UPPER(_bm_model_variable_name);
    if(productSelectionProduct_all <> ""){
        like_selModel = "%" + productSelectionProduct_all + "%";
        allRecs = bmql("SELECT distinct M.ItemCategory FROM Oracle_BomItemMap M INNER JOIN Oracle_BomItemDef D
                        ON D.VariableName = M.BomItemVarName WHERE D.RootVariableName=$cpqModel
                        AND M.ItemType = 'Accessories' AND M.ConfigAttrValue LIKE $like_selModel");
        for rec in allRecs{ retVal = retval + get(rec, "ItemCategory") + "|^|"; }
    }
    return retVal;
  ```
- The generic single-value auto-default rule `Default Values If only one value is available (Portable)` (rule id 17691443441) has an explicit action-target list (attribute ids 17691442148, 172, 156, 160, 378, 380, 176, 190, 194, 170) that does **not** include 17691442430 — so there is no confirmed active rule that force-selects a single accessories category.
- **Verdict: NEEDS MORE DATA.** Value would only be correct if `Oracle_BomItemMap` has exactly one `ItemCategory` row = `ANTENNAS CABLE OTHER` for `APX NEXT ENHANCED`; table rows not verified in this pass.

### 5. carrierSelectionMultiSelect_astro (attribute id `18302531460`)
- Every value-setting rule found for this id is customer-specific:
  - `Force VERIZON carrier selection` (rule id 18654807104, status=1):
    ```
    condition: 1 AND 2 AND 3 AND 4
    input: attribute 17691442356 (customerUIN) value1="H55TGT9PW8BN"
    input: attribute 18374452019 value1="true" (dual-sim flag)
    input: attribute 18302531460 (self) value1="VERIZON"
    script: retVal = "VERIZON"; return retVal;
    ```
  - `Default verizon for Dual sim` (rule id 18654807102, status=1): same customerUIN + dual-sim gating, no script body (action `function_id=-1`, implying a fixed set-value, not scripted).
  - `Require Secondary sim if primary sim is verizon` (constraint, rule id 17691443827) and `Hide Secondary Sim if Primary Sim is not Verizon` (rule id 17691443823) both confirm Carrier is a live, answerable field in this product line, not one that silently resolves.
- No rule targeting this attribute for a generic US/Enhanced/5G scenario (no customerUIN gate) was found among all 20 rule hits.
- **Verdict: INCORRECT.** ATT/FirstNet is not derivable from any traced rule for this context; the only active rules that touch this field are customer-specific and would force VERIZON, not ATT/FirstNet. This is consistent with the second screenshot's evidence that Wireless Carrier is a genuine mandatory, unanswered dropdown for this device family — it should not appear as a pre-resolved key in `configData` for this scenario at all.

### 6. additionalSystemEnhancementFeatureType_astro (attribute id `17691442162`)
- The only rule found that sets value `DISABLE CLOUD SERVICES` is:
  ```
  Rule: Default Disable Cloud Services for customerUIN 1070001185 for APX Next intl fed israel for Custom (id 17691442961)
  condition_expression: 1 AND 2 AND 3 AND 4 AND 5
  input: attribute 39427019 (productSelectionProduct_all) value1="APX NEXT INTL FED"
  input: attribute 39426962 (country) value1="IL"
  input: attribute 39426963 (customerUIN) value1="1070001185"
  input: attribute 17691442152 (package type) value1="CUSTOM"
  ```
  This requires product = `APX NEXT INTL FED` (not `APX NEXT ENHANCED`), country = Israel (not US), and a specific customer UIN and CUSTOM package type — none of which match the given scenario.
- The only other active rule referencing this attribute for constraint purposes is `Do not allow CLOUD RC` (rule id 17691442901, constraint, `rule_type=2`) — a restriction, not a default.
- **Verdict: INCORRECT.** No traced rule justifies `DISABLE CLOUD SERVICES` for US + `APX NEXT ENHANCED`; the only matching rule text is scoped to an unrelated INTL/Israel/customer-specific case.

## Sequence Order (dependency-ordered)

1. **Country = United States** (customer input) — gates most US-only rule branches (`Restrict Application Services if Duration Blank APX Next`, `Constrain Delete Narrow-banding only to US...`, etc.).
2. **hWVersion_astro = "NEXT ENHANCED LTE PLUS 5G"** (customer input, no active default rule fires).
3. **Rule 17691443811** `Restrict APX Next Product Selection based on HW Version selection` — evaluates on hWVersion_astro, narrows `productSelectionProduct_all` options to `{APX NEXT ENHANCED, APX NEXT XE 4G LTE PLUS 5G}`.
4. **productSelectionProduct_all = "APX NEXT ENHANCED"** (customer input from the narrowed list).
5. **Rule 18131370887** `Constraint solution set based on product` — queries `Oracle_BomItemMap`/`Oracle_BomItemDef` on `productSelectionProduct_all` to compute allowed `accessoriesSolutionSet_astro` values.
6. **Rule 18654807132** `Restrict Related Service Type` — queries `relSoftAndServcParts` on `productSelectionProduct_all` (via `_bm_model_variable_name` fallback) to compute allowed `relatedServicesType_astro` values.
7. **Rule 17691442855** `Populate Related Services And Software Array` — depends on step 6's resolved model, populates related-services sub-attribute arrays from `hiddenMasterStringForRelatedServices_astro`.
8. **(Not applicable in this scenario)** `Default Disable Cloud Services...` (17691442961) and `Force VERIZON carrier selection` (18654807104) / `Default verizon for Dual sim` (18654807102) — these are evaluated but their conditions are false for this US/Enhanced/APX NEXT ENHANCED/generic-customer context, so they do not fire and should leave `carrierSelectionMultiSelect_astro` unresolved and `additionalSystemEnhancementFeatureType_astro` un-defaulted to Cloud-related values.

## Tables Required

| Table (as used in BML `bmql()` calls) | Purpose | Coverage confirmed for this scenario? |
|---|---|---|
| `relSoftAndServcParts` (columns include `cpqModel`, `serviceType`) | Distinct related-service types per CPQ model — drives `relatedServicesType_astro` | Not verified in this pass |
| `Oracle_BomItemMap` joined to `Oracle_BomItemDef` (`ItemType='Accessories'`, `ConfigAttrValue`, `ItemCategory`, `BomItemVarName`/`VariableName`, `RootVariableName`) | Distinct accessory `ItemCategory` values per model — drives `accessoriesSolutionSet_astro` | Not verified in this pass |
| `Oracle_BomItemMap`/`Oracle_BomItemDef` with `ItemType = 'Related Services'` (columns `PartNumber`, `ItemCategory`, `ConfigAttrValue`, `ConfigAttrVarName`, `ConfigAttrValue1`, `ConfigAttrVarName4`, `ConfigAttrValue4`) | Related services/software parts list, filtered further by `productSelectionProduct_all` and `ultimateDestinationCountry` | Referenced by `Populate Related Services And Software Array`; row-level coverage not verified |

No data table in this export was found to drive `carrierSelectionMultiSelect_astro` or `additionalSystemEnhancementFeatureType_astro`'s "Disable Cloud Services" value for a generic US scenario — both are handled purely by BML rule conditions, and none of those conditions match the given scenario.
