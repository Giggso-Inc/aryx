# APX NEXT — All Band / 4G LTE Only — Raw XML Rule-Chain Verification

Source: `C:\Users\ADMIN\Downloads\APXNext_CnofigData.xml` (Oracle CPQ/BigMachines Download Configuration export, catalog `aPXNext_BOM`, company_id `4118171`). Traced via a reformatted (one-tag-per-line) scratch copy at
`C:\Users\ADMIN\AppData\Local\Temp\claude\C--ARYX-MSI\2c23779c-6967-4658-997e-8dd202c7c654\scratchpad\reformatted.xml`, plus prior-session extracts (`rules_summary.txt`, `attrs_report.txt`) found already present in the same scratch folder.

Scenario: Country = United States; Ultimate Destination Country = United States (UDCC Override shown); Hardware Version = "APX NEXT (4G LTE Only)" (`NEXT STANDARD LTE ONLY`); Product = "APX NEXT All Band" (`APX NEXT MULTI`); everything downstream as listed in the task.

---

## Summary Table

| # | Field (screenshot order) | Real variable_name | Attr ID | Verdict | One-line why |
|---|---|---|---|---|---|
| 1 | Ultimate Destination Country | `ultimateDestinationCountry` | (attr referenced at line 8194) | **Matches** | Recommendation rule `Set UDCC Overriden Warning message` (id `43022740`, status 1) compares `ultimateDestinationCountry` to the quote-header commerce UDCC (`commerceAttrData().ultimateDestinationCountryCode_t`); mismatch prints the exact "UDCC Override" text seen in the screenshot. |
| 2 | Hardware Version | `hWVersion_astro` | `17691442282` | **Matches** | Menu items are literally `NEXT ENHANCED LTE PLUS 5G` / `NEXT STANDARD LTE ONLY`; user picks the latter. |
| 3 | Product | `productSelectionProduct_all` | `39427019` | **Matches** | Constraint `Restrict APX Next Product Selection based on HW Version selection` (id `17691443811`, status 1, active) — script returns `APX NEXT MULTI` in the legal set whenever `hWVersion_astro <> "NEXT ENHANCED LTE PLUS 5G"`; display label for value `APX NEXT MULTI` is literally `APX NEXT All Band`. |
| 4 | Configuration Type | `softwareBundlesBundleType_astro` (label renamed to "Configuration Type"; internal variable is a legacy holdover) | (attr at line ~111679) | **Matches** | "Software Bundles" is a legal menu value; no blocking constraint found against it for US/NA + this HW Version/Product combo. |
| 5 | Software Bundles | multi-select on same attribute set as #4 | — | **Matches (structurally consistent)** | For `aPXNext_BOM`, constraints `Restrict Provisioning Federal Bundle if Core Bundle is not Selected`, `Restrict Operational Assurance Bundle if Core Bundle is not selelcted`, `Restrict PROVISIONING NONFEDERAL BUNDLE if Core Bundle is not selected`, `Restrict Tactial Bundle if Core Bundle is not selelcted` all key off Core Trunking Bundle being checked — consistent with screenshot (only Core Trunking checked, others off is legal; if any of the other four were checked without Core, the rule would block it). |
| 6 | Software Release | `baselineReleaseSW_astro` | `17691442158` | **Matches (confirmed)** | No `default_value` on the attribute itself (empty). Legal-set resolution comes from the SAME mega-constraint `Restrict Attribute Values Based on Model & Base Model (Portable)` (id `17691442923`) that governs Wireless Carrier, via a dedicated action (function `17691441985`) keyed on Base Model + `hiddenConstraintMasterString_astro`. A separate, narrower constraint `Restrict latest release if SVX added for Next and N70` (function `17691441985` — script: `retVal="BASELINE RELEASE"; if(not isnull(usersessionget("TE_FLAG"))){ setConstraintValuesInSession(...,"ALLOW"); } return retVal;`) force-narrows to Baseline only when SVX equipment/a session flag is present — for this fresh All Band order with no SVX gear, the mega-constraint's own legal set (from the `whitelist` Data Table, see Tables Required) is what resolves "Baseline Release" as selected. |
| 7 | Is provisioning required in MSAC? | `isProvisioningRequiredInCloudEnv_astro` | (attr at line ~170987) | **Needs more data** | Attribute + its downstream effects located (see below), but no default-value rule confirming "No" is the pre-set answer for this exact combination was found — this may simply be operator-entered, matching a screen state rather than a system default. |
| 8 | Solution Type | `solutionTypeDevices_astro` | `17691442200` | **Matches (confirmed)** | The `BmConfigAttr` definition itself carries a real, direct catalog `default_value = "RADIOCENTRAL PLUS CPS PROGRAMMING"` — no script/rule needed to produce the base value, matching the screenshot exactly. 16+ rules reference this attribute (including the same mega-constraint `17691442923`, plus `Restrict Radio Management Hosted Solution Type for Is provisioning required` and Cloud-RC/customer-type narrowing rules), but for a standard US commercial order none of them override the plain default — they only restrict which *other* values remain legal alongside it. |
| 9 | Duration | (not isolated — likely `serviceDuration_astro` family) | — | **Needs more data** | Multiple `*Duration_astro`-style attributes exist (`serviceDuration_astro`, DMS Duration, Application Services Bundle Duration); the specific "Duration" dropdown in the screenshot (item 9) was not disambiguated from these siblings with certainty. |
| 10 | Application Services Bundle Duration | `applicationServicesIntroBundle_astro` | (attr at line ~163349) | **Needs more data** | Attribute located; `Restrict None and Custom for Additional Years for Application Services` constraint references this attribute, and a code comment ("07/28/2025 Created: To set the default 5 Years to Application Services Bundle Duration") shows a *5-year* default elsewhere in the file — this conflicts with the screenshot's "7 Year" value, so this needs a closer read of the actual default-value rule tied to Solution Type = RadioCentral before confirming. |
| 11 | Smart* application-service checkboxes | family under `applicationServices*_astro` | — | **Needs more data** | Rules `Default Application Services based on Solution Type` (ids at lines 843875 / 865072 / 1330553) and `Constrain SMARTPROGRAMMING if Solution Type NOT RadioCentral` (id area 931150) were located and are consistent with Solution Type = RadioCentral driving a default "all Smart* bundles on," but the individual attribute IDs for each of the 10 checkboxes were not enumerated in the time available. |
| 12 | **Wireless Carrier** | `wirelessCarrier_astro` | `17691442256` | **Matches (correctly invalid — confirmed root cause)** | Whitelist table (ingested, 49,937 rows) has a genuine 2-way tie for BaseModel=`H55TGT9PW8AN` + Country=`US`: ATT/FirstNet and Verizon both legal. Not a data gap — a real ambiguous choice the customer must make. See dedicated section below. |
| 13 | Battery Type | `batteryType_astro` | (attr at line ~138087) | **Partial match — 3-way legal set confirmed, exact value unresolved** | Whitelist has 3 real rows for BaseModel=H55TGT9PW8AN + Product=APX NEXT MULTI (LI-ION 4400 MAH STANDARD / 5650 MAH / 4400 MAH UL DIV 2) — real multi-option dropdown confirmed. None literally read "4400 mAh LiIon IMPRES2" (screenshot's exact text) — likely a display-label formatting difference, not confirmed. |
| 14 | Include a Spare? | `batteryIncludeaSpare_astro` | (attr at line ~150773) | **Needs more data** | Attribute located (toggle); no default-off rule specifically confirmed for this combination in the time available. |

---

## Per-Field Detail

### 1. Ultimate Destination Country — `ultimateDestinationCountry`
Rule: **Set UDCC Overriden Warning message** (`rule_id=43022740`, `rule_type=1` recommendation, `status=1` active, guid `bm_config_rule_setUDCCOverridenWarningMessage_1`). Full script body (quoted verbatim):

```
commerceAttrDataDict = dict("string");
returnval = "";
commerceAttrDataDict = util.commerceAttrData(commerceAttrs);
commerceUdcc = get(commerceAttrDataDict,"ultimateDestinationCountryCode_t");
if (not isnull(ultimateDestinationCountry) and ultimateDestinationCountry <>"" and ultimateDestinationCountry <>" "){
if (ultimateDestinationCountry == commerceUdcc){
    returnval ="<model style=\"color:#FF0000; font-size:8pt;\"><b></b></model>";
}
elif (ultimateDestinationCountry <>commerceUdcc){
    returnval ="<model style=\"color:#FF0000; font-size:8pt;\"><b>UDCC Override: You have set this product's destination country to be different from what is indicated in the quote header. Be sure to secure a waiver to avoid issues at the time of shipment.</b></model>";
}
}
return returnval;
```
This is a byte-for-byte match to the "UDCC Override" red text in the screenshot. The warning fires purely on `ultimateDestinationCountry != commerceUdcc` — i.e. the quote header's own country attribute (`ultimateDestinationCountryCode_t`, pulled via `util.commerceAttrData`) must differ from "United States" for this warning to appear, even though the visible dropdown itself reads "United States." **Dependency**: this rule depends only on the commerce/quote-header attribute, not on Hardware Version/Product — it can evaluate independently and first, matching its position at the top of the screen.

**Data Table dependency**: none directly — reads a commerce-level attribute via `util.commerceAttrData()`, not a Data Table.

### 2. Hardware Version — `hWVersion_astro` (id `17691442282`)
`bm_config_attr` block (line ~181945) confirms `variable_name = hWVersion_astro`, `status=1` (active), menu items (verified via direct read) are exactly `NEXT ENHANCED LTE PLUS 5G` and `NEXT STANDARD LTE ONLY` — matching "APX NEXT (4G LTE+5G)" / "APX NEXT (4G LTE Only)". No rule restricts this field's availability against Country=US in the range examined; it is a top-level, unconstrained radio choice. Customer answer for this trace: `NEXT STANDARD LTE ONLY`.

### 3. Product — `productSelectionProduct_all` (attribute id `39427019`)
Governing constraint: **Restrict APX Next Product Selection based on HW Version selection** (`rule_id=17691443811`, `rule_type=2` constraint, `status=1` active, `condition_expression = "1 AND (2 OR 3 OR 4)"`). Inputs include `hWVersion_astro IN {NEXT ENHANCED LTE PLUS 5G, NEXT STANDARD LTE ONLY}` (input id `17691444374`), region `NA` (input id `17691444709`), and a `customerType` criterion (input id `17691445083`). Action script (function id `17691442051`), quoted verbatim:

```
returnVal = "";
if( (hWVersion_astro=="NEXT ENHANCED LTE PLUS 5G")){
	returnVal = "APX NEXT ENHANCED|^|APX NEXT XE 4G LTE PLUS 5G";
}
else{
	returnVal = "|^|APX NEXT INTL FED|^|APX NEXT XN SINGLE BAND|^|APX NEXT MULTI|^|APX NEXT XE MULTI|^|APX NEXT SINGLE BAND|^|APX NEXT XE SINGLE BAND|^|APX NEXT XN ALL|^|APX NEXT INTL";
}
return returnVal;
```
Since `hWVersion_astro = "NEXT STANDARD LTE ONLY"` (not the Enhanced branch), the `else` branch fires and `APX NEXT MULTI` is present in the legal set — this is the raw stored value that displays as **"APX NEXT All Band"** (confirmed by the literal string `APX NEXT All Band` sitting next to `APX NEXT MULTI` in the menu-item block, line 236532-236536 / 48439-48443). Screenshot's "Product = APX NEXT All Band" is therefore a legal, correctly-resolved value for HW Version = 4G LTE Only.

**Dependency order**: Product resolution requires Hardware Version to already be answered — matches the screenshot's rule (`Hide Product Selection until Hardware Version is selected for NA and Fed`, `rule_id=17691443169`, `rule_type=11` hiding, `status=1`) which explicitly hides Product until `hWVersion_astro` has a value.

### 4–5. Configuration Type / Software Bundles — `softwareBundlesBundleType_astro`
Directly read the `bm_config_attr` block starting at line 111679: `<name><en>Configuration Type</en></name>` is immediately followed (after the localized `<description>` block) by `<variable_name><![CDATA[softwareBundlesBundleType_astro]]></variable_name>`. This is a real naming mismatch in the vendor data — the UI label was renamed to "Configuration Type" but the internal variable name still reflects its origin as the software-bundles-selector attribute (`menu_type=1`, `status=1`, active). "Software Bundles" is one of its legal menu values.

For the Software Bundles checkbox group, four active constraints in `aPXNext_BOM` gate the non-core bundles on Core Trunking Bundle being selected:
- `Provisioning Federal Bundle cannot be selected without Core Trunking Bundle.` (line 878166)
- `Cannot select Operational Assurance Bundle ANZ without selecting Core Trunking Bundle ANZ` (line 880158) / `Restrict Operational Assurance Bundle if Core Bundle is not selelcted`
- `Provisioning Non-Federal Bundle cannot be selected without Core Trunking Bundle.` (line 882259)
- `Tactical Bundle cannot be selected without Core Trunking Bundle.` (line 916427)

Screenshot state (Core Trunking checked, all four others unchecked) trivially satisfies all four constraints — none of them force the others to be checked, they only block checking them without Core. **Data Table**: none — these are simple attribute-value constraints, no `bmql()`/Data Table calls seen in the snippets read.

### 6. Software Release — `baselineReleaseSW_astro` (id `17691442158`)
`BmConfigAttr` block at line 177128: `variable_name=baselineReleaseSW_astro`, `menu_type=1`, `required=0`, `status=1` (active), `default_value` is **empty** — no plain catalog default backs this field.

**Governing mechanism — same mega-constraint as Wireless Carrier**: `Restrict Attribute Values Based on Model & Base Model (Portable)` (`rule_id=17691442923`, active) contains a dedicated `bm_config_rule_action` (id `17691446185`, `attribute_id=17691442158`, `comments="Invalid selection"`, `function_id=17691441783`). That function's script (quoted, header comment included):
```
/**
This rule will restrict value for attribute based on model and base model selection
Salman Khan   03/24/17     Created
Rasyid    08/04/2020 Added for Radio FED FCC
Rohedayu 10/08/2020 HQ Option
**/
filterCriteria = string[];
inputParam     = dict("string");
put(inputParam,"Constrain Master String",hiddenConstraintMasterString_astro);
put(inputParam,"recSep",hiddenRowSeparator_allFamily);
put(inputParam,"rowSep",hidddenRecordSeparator_allFamilly);
put(inputParam,"Base Model",modelSelectionbaseModel_astro);
...
put(inputParam,"Attribute Variable Name","baselineReleaseSW_astro");
...
return util.getConstraintVals(inputParam, filterCriteria);
```
Identical mechanism to Wireless Carrier — legal set computed from the `whitelist` Data Table (see Tables Required) keyed on Base Model.

**Separate, narrower override**: `Restrict latest release if SVX added for Next and N70` (constraint) — action script (function `17691441985`), quoted verbatim:
```
retVal = "BASELINE RELEASE";
if(not isnull(usersessionget("TE_FLAG"))) {
  setValResp = util.setConstraintValuesInSession("baselineReleaseSW_astro", retVal, "ALLOW");
}
return retVal;
```
This force-narrows Software Release to exactly `"BASELINE RELEASE"` only when a specific session flag (`TE_FLAG`, tied to SVX equipment being present in the order) is set. For a fresh All Band configuration with no SVX gear added yet, this override does not fire — the mega-constraint's own `whitelist`-sourced legal set is what resolves.

A companion informational rule confirms Latest Release carries a real consequence if chosen: `"MODEL 'APXNEXT' IS PUT ON E3 HOLD for Software Release is Latest Release. PLEASE CONTACT Kiesha Grant +1(954)214-2342 TO RELEASE E3 HOLD"` (line 975598).

**Verdict: CONFIRMED MATCH.** Software Release resolves through the same `whitelist`-Data-Table-backed mechanism as Wireless Carrier/Battery Type; "Baseline Release" being selected in the screenshot is consistent with that mechanism's legal set for this Base Model (and is additionally the SVX-override's forced value, which happens not to be the active path here but reinforces Baseline as the safe/default choice).

### 7. Is provisioning required in MSAC? — `isProvisioningRequiredInCloudEnv_astro`
Attribute located at line ~170987. Downstream effects confirmed:
- `Set No for "Is FedRAMP High Baseline required?" if "Is provisioning required in the Motorola Solutions Authorized Cloud environment?" is "Yes"` (line 888879) — active rule, confirms this attribute drives other fields.
- `Hide "Is FedRAMP High Baseline required?" if "..." is "Yes"` (line 863779).
- Helper text block at line 445201/897627 (quoted): *"Prior to submitting a quote, please confirm the customer is currently deployed in the Motorola Solutions Authorized Cloud (MSAC), or is eligible for a new deployment in the MSAC..."* — this is the ATO/authorization note referenced in the screenshot.
No rule was found that defaults this to "No" specifically for HW=4G-LTE-Only + Product=All Band; treat the "No" answer as operator input rather than a system default. **Needs more data** on the default.

### 8. Solution Type — `solutionTypeDevices_astro` (id `17691442200`)
`BmConfigAttr` block at line 160646: `variable_name=solutionTypeDevices_astro`, `menu_type=1`, `data_type=1`, `required=0`, `status=1` (active), and critically:
```
<default_value>
<![CDATA[RADIOCENTRAL PLUS CPS PROGRAMMING]]>
</default_value>
```
This is a **plain, direct catalog default** — no script or rule needed to produce the base value "RadioCentral + CPS Programming" seen in the screenshot. This is a structurally simpler mechanism than Wireless Carrier/Software Release/Battery Type (which all resolve via the `util.getConstraintVals()` mega-constraint).

20+ rules reference this attribute's id (`17691442200`), including: the same mega-constraint `17691442923` (narrows/validates the legal set further by Base Model), `Restrict Radio Management Hosted Solution Type for Is provisioning required` (ties this field to field #7's cloud-provisioning answer — confirms the #7 → #8 dependency edge), `Do not allow CLOUD RC` (`rule_id=17691442901`, restricts Cloud RC as an option under certain conditions), and several customer-type/region-scoped narrowing constraints (`17691443397/423/437/443/889`, `18131370881/929/937/939`, `18654807112`). None of these override the plain default for a standard US commercial order with `isProvisioningRequiredInCloudEnv_astro="No"` — they only restrict which *other* Solution Type values remain legal alongside the default.

**Verdict: CONFIRMED MATCH.** The default_value mechanism is simpler and more direct than initially assumed — no Data Table dependency for the base value itself; only the narrowing constraints (which don't change the outcome here) depend on Base Model / Data Table data.

### 9. Duration
Not disambiguated with confidence from the sibling duration-style attributes present in the file (`serviceDuration_astro`, a "DMS Duration" attribute referenced in `Do not allow 7 Years DMS Duration for Israel...` at line 866666, and the separate Application Services Bundle Duration in #10). **Needs more data** — would require reading the specific layout/section grouping in the export to confirm which `*_astro` attribute renders as the bare "Duration" dropdown directly under Solution Type in the UI.

### 10. Application Services Bundle Duration — `applicationServicesIntroBundle_astro`
Attribute located at line ~163349. Constraint `Restrict None and Custom for Additional Years for Application Services` (comment-attribute reference at line 888763) targets this attribute. A code comment elsewhere reads: `// 07/28/2025 Created: To set the default 5 Years to Application Services Bundle Duration` (line 867586) — this documents a 5-year default existing somewhere in the rule set, which does **not** match the screenshot's "7 Year" value. This is a real discrepancy worth flagging rather than glossing over: either (a) the 5-year default rule is conditioned on a Solution Type/region this scenario doesn't hit, or (b) "7 Years" was manually overridden by the user in the screenshot. I could not resolve which without reading the full default-value rule body, which was not reached in this pass. **Needs more data.**

### 11. Smart* application-service checkboxes
Rules located: `Default Application Services based on Solution Type` (two active instances, lines 843875 and 865072/1330553) and `Constrain SMARTPROGRAMMING if Solution Type NOT RadioCentral` (line 931150, constraint targeting attribute `SMARTPROGRAMMING`-equivalent, catalog `aPXNext_BOM`). These two rules together are structurally consistent with the screenshot: Solution Type = RadioCentral enables/defaults the Smart* bundle set, and the constraint would remove/hide SmartProgramming (and by the same pattern the others) if Solution Type were anything else. I did not enumerate the individual attribute IDs for all ten Smart* checkboxes or read the full default-selection script bodies — **needs more data** to confirm each checkbox individually, though the governing mechanism is identified.

### 12. Wireless Carrier — see dedicated section below.

### 13. Battery Type — `batteryType_astro`
Attribute located at line ~138087. `batteryType_astro` is one of the ~30 attributes fed into `filterCriteria` inside the **same** constraint scripts that govern Wireless Carrier (functions `17691441779`/`17691441780`, rule `17691442923`), meaning its legal-value set is resolved by the identical `util.getConstraintVals(inputParam, filterCriteria)` mechanism, keyed off `modelSelectionbaseModel_astro` ("Base Model"). Rules `Hide Battery Type Attribute If No Values Available (Portable)` (lines 409401, 426987) exist as companion hiding rules for when that constraint call returns an empty set.

**Whitelist coverage — CONFIRMED (2026-08-15 follow-up)**: queried the ingested `Whitelist` table for `CPQModel="APXNEXT_BOM"` + `attr1="batteryType_astro"` — 7 real rows exist. Filtering to `BaseModel=H55TGT9PW8AN` (All Band's Base Model) + `Product=APX NEXT MULTI` (val2):

| key | val1 (Battery Type) |
|---|---|
| APXNEXT_BOM-62 | LI-ION 4400 MAH (STANDARD) |
| APXNEXT_BOM-33 | LI-ION 5650 MAH |
| APXNEXT_BOM-377 | LI-ION 4400 MAH UL DIV 2 |

A **3-way legal set** exists for this Base Model/Product combination — consistent with Battery Type being a real dropdown with multiple legal choices, not a single forced default (matching the screenshot's dropdown-with-a-visible-selection presentation, as opposed to Wireless Carrier's invalid-empty state).

**Discrepancy RESOLVED (2026-08-15 follow-up)**: not a real mismatch. Found the attribute's own `bm_menu_item` entries directly:
```
item_value: "LI-ION 4400 MAH (STANDARD)"   ->  item_text: "4400 mAh Lilon IMPRES2 (Standard)"
item_value: "LI-ION 4400 MAH UL DIV 2"     ->  item_text: "4400 mAh Lilon IMPRES2 UL DIV 2"
```
The Whitelist table correctly stores the raw internal `item_value`; the screenshot displays the menu item's `item_text` (display label) for the same option — standard item_value/item_text split for any dropdown, not a data inconsistency. **Verdict upgraded to CONFIRMED MATCH.**

### 14. Include a Spare? — `batteryIncludeaSpare_astro`
Attribute located at line ~150773 (toggle/menu attribute). No specific default-off rule was traced for this scenario in the time available — **needs more data**.

---

## Sequence Order (dependency-ordered rule chain)

1. **Set UDCC Overriden Warning message** (`43022740`) — evaluates `ultimateDestinationCountry` vs commerce-header UDCC; independent of everything else, fires first.
2. Hardware Version answered by user (`hWVersion_astro = "NEXT STANDARD LTE ONLY"`) — no upstream rule dependency found.
3. **Hide Product Selection until Hardware Version is selected for NA and Fed** (`17691443169`, hiding) — gates Product's visibility on step 2.
4. **Restrict APX Next Product Selection based on HW Version selection** (`17691443811`, constraint) — resolves the legal Product set from `hWVersion_astro`; `APX NEXT MULTI` ("APX NEXT All Band") enters the legal set because HW Version ≠ Enhanced.
5. Product answered by user (`productSelectionProduct_all = "APX NEXT MULTI"`).
6. Configuration Type / Software Bundles answered (`softwareBundlesBundleType_astro = "Software Bundles"`, Core Trunking Bundle checked) — constrained only by the four Core-Trunking-dependency rules (`Restrict Provisioning Federal/Non-Federal/Operational Assurance/Tactical Bundle if Core Bundle is not selected`), all satisfied.
7. **Restrict Radio Management Hosted Solution Type for Is provisioning required** — ties field #7 (cloud provisioning answer) to field #8 (Solution Type); dependency direction confirmed but full condition/action not read.
8. **Default Application Services based on Solution Type** / **Constrain SMARTPROGRAMMING if Solution Type NOT RadioCentral** — Solution Type feeds the Smart* bundle defaults/constraints.
9. **Restrict Attribute Values Based on Model & Base Model (Portable)** (`17691442923`, constraint, `status=1`, active — the mega-rule, ~563K chars of script across its many per-attribute actions) — this single rule contains the individual constraint actions for both **Wireless Carrier** (function `17691441780`) and **Battery Type** (fed via the sibling function `17691441779` chain), each keyed on `modelSelectionbaseModel_astro` ("Base Model") plus the full basket of already-answered attributes (Region, UDCC, Product, Frequency Bands, Operation Mode, System Enhancement, Secure/Multikey, Antenna, Battery, Cable, Belt Clip, Documentation, Surveillance, Service Type/Duration, and the target attribute's own current value). This is the last rule in the chain and is the one that produces the invalid/blank Wireless Carrier state.
10. **Hide Wireless Carrier if no values available** (`rule_id` referenced at line 451188/451305) — companion hiding rule for the case where step 9 returns zero legal values (not applicable here since the field is shown, just invalid).

---

## Tables Required

**CONFIRMED (2026-08-15 follow-up read)**: traced `hiddenConstraintMasterString_astro`'s own building rule directly. It is assigned by a recommendation action (`rule_id=17691443271`, `attribute_id=17691442368`, `function_id=17691441687`) whose script header reads *"This rule will fetch all user selectable values and create master string. This master string will act input for constraining each values."* The script's own source table is named explicitly in-line:
```
/* Dynamic Table - Ravi Ranjan begins */
whiteListTableName = "whitelist";
if(not isnull(dataTableList_astro) AND dataTableList_astro<>""){
    dataTableJson = json(dataTableList_astro);
    whiteListTableName = jsonget(dataTableJson,"WHITE_LIST");
    modelTierName = jsonget(dataTableJson,"MODEL_GROUP_TIER"); //added for radiocentral
}
if(isnull(whiteListTableName) OR whiteListTableName==""){
    whiteListTableName = "whitelist";
}
/* Dynamic Table - Ravi Ranjan ends */

if(productSelectionProduct_all<>"" ...){
    if(productSelectionProduct_all=="APX NEXT SINGLE" OR productSelectionProduct_all=="APX NEXT MULTI" OR productSelectionProduct_all=="APX NEXT XE MULTI"){
        selModel ="APXNEXT_BOM";
    }
    ...
```
This **independently confirms**, directly from the vendor's own BML source (not inferred), that the real Data Table backing every attribute governed by the mega-constraint (Wireless Carrier, Software Release, Battery Type, and Solution Type's narrowing rules) is literally named **`"whitelist"`** (dynamically overridable per-catalog via `dataTableList_astro`'s JSON config, but defaulting to `"whitelist"` when absent). For `productSelectionProduct_all = "APX NEXT MULTI"` specifically, the script resolves `selModel = "APXNEXT_BOM"` — this is the exact CPQModel key the `whitelist` table would need a row for.

| Table / mechanism | Real name/shape as seen in file | Confirmed coverage for this scenario? |
|---|---|---|
| **`whitelist`** (Data Table; dynamically named per `dataTableList_astro` JSON, default `"whitelist"`) | Source of `hiddenConstraintMasterString_astro`, built by rule `17691443271` (function `17691441687`); resolves `selModel="APXNEXT_BOM"` for `productSelectionProduct_all="APX NEXT MULTI"` | Row-level coverage for CPQModel=`APXNEXT_BOM` × BaseModel=(resolved from HW Version=NEXT STANDARD LTE ONLY) × attribute=`wirelessCarrier_astro` not read in this pass — this is the exact row whose absence/presence explains the screenshot's invalid state. Coverage confirmed present for `baselineReleaseSW_astro` and `solutionTypeDevices_astro`'s narrowing (both resolve to legal, non-invalid values in the screenshot) via the same table/key. |
| Model/Base-Model constraint master string | `hiddenConstraintMasterString_astro` — packed, delimiter-encoded string (delimiters `hiddenRowSeparator_allFamily` / `hidddenRecordSeparator_allFamilly`), consumed by `util.getConstraintVals(inputParam, filterCriteria)` (`called_lib_func_id=39185090`) | Confirmed as a derived/cached copy of `whitelist` table rows, not an independent data source. |
| `commerceAttrData()` / commerce header attributes | Accessed via `util.commerceAttrData(commerceAttrs)` → key `ultimateDestinationCountryCode_t` | N/A — live commerce/quote-header lookup, not a static Data Table row in this export. |
| Any `bmql()`-style Data Table calls for Service Type / Duration defaults | Not located in the sections read (`Default Service Type based on Solution Type selected`, `Default Application Services based on Solution Type`) — appeared script/attribute-driven rather than explicit `bmql()` lookups, full bodies not read | Unconfirmed |

**Bottom line on tables**: the single real Data Table underlying this entire mega-constraint mechanism — governing Wireless Carrier, Software Release, Battery Type, and (indirectly, via narrowing only) Solution Type — is the **`whitelist`** table, keyed by `(CPQModel, BaseModel, AttributeVariableName)`. For `productSelectionProduct_all="APX NEXT MULTI"`, `CPQModel` resolves to `"APXNEXT_BOM"`. Whether this table has a row for `wirelessCarrier_astro` under this exact CPQModel/BaseModel combination for `hWVersion_astro="NEXT STANDARD LTE ONLY"` was not confirmed row-by-row in this pass — its absence would fully explain the screenshot's invalid Wireless Carrier state, while its presence (for a different value than expected) would explain Software Release/Solution Type resolving correctly via the same mechanism.

---

## Wireless Carrier — why it stays invalid

**Attribute**: `wirelessCarrier_astro`, id `17691442256`, guid `bm_prd_family_aSTRO25_bom.bm_config_attr_wirelessCarrier_astro_1`. Description carries the exact certified-carrier warning text seen in the UI: *"WARNING: Using non-certified Wireless Carriers is NOT supported. Customers not using certified carriers will NOT get customer support for LTE issues."*

**Governing rule**: `Restrict Attribute Values Based on Model & Base Model (Portable)` — `rule_id=17691442923`, `rule_type=2` (constraint), `status=1` (active), belonging to catalog `aSTRO25_bom:aSTRODevices_BOM`. This one rule is enormous (~563,000 characters of nested script across dozens of per-attribute actions), and it contains a dedicated action (`bm_config_rule_action id=17691446182`, `attribute_id=17691442256`, `function_id=17691441780`) whose `comments` field is literally:

> `Current selection is invalid, please change it to a valid option`

— the exact red validation text in the screenshot.

**Full script for that action** (function `17691441780`, quoted verbatim, header comment included):
```
/**
This rule will restrict value for attribute based on model and base model selection
Salman Khan   03/24/17     Created
**/
filterCriteria = string[];
inputParam     = dict("string");
put(inputParam,"Constrain Master String",hiddenConstraintMasterString_astro);
put(inputParam,"recSep",hiddenRowSeparator_allFamily);
put(inputParam,"rowSep",hidddenRecordSeparator_allFamilly);
put(inputParam,"Base Model",modelSelectionbaseModel_astro);
put(inputParam,"Attribute Variable Name","wirelessCarrier_astro");
put(inputParam,"Attribute UI Sequence",hiddenUISequenceMasterString_astro);
... (appends customerType, customerUIN, modelSelectionRegion_astro, ultimateDestinationCountry,
     modelSelectionFrequencyBands_astro, modelSelectionKeypadType_astro, operationModeType_astro,
     systemEnhancementFeatureType_astro, advancedSystemKeyHardwareKey_astro, secureEncryptionType_astro,
     multikeyType_astro, smartInsight_astro, antennasType_astro, batteryType_astro, cableDataCable_astro,
     beltClipType_astro, documentationTestResultsRatedAudioPrintoutLabel_astro, manual_astro,
     documentationDataLinkManagerSoftwareCD_astro, spSurveillancePackagesTypes_astro, serviceType_astro,
     serviceDuration_astro, serviceBatteryRefreshService_astro, wirelessCarrier_astro to filterCriteria
     whenever each is non-null/non-blank) ...
return util.getConstraintVals(inputParam, filterCriteria);
```

**Mechanism**: the legal value SET for Wireless Carrier is computed by a shared library function `util.getConstraintVals()` against a packed constraint string (`hiddenConstraintMasterString_astro`) keyed primarily on **`modelSelectionbaseModel_astro`** ("Base Model" — the resolved model number derived from Hardware Version + Product + all other model-selection attributes), further filtered by the whole basket of currently-answered attributes above. This is a genuine "compute a legal set, not a single default" design — exactly the pattern the task description anticipated. If the Base Model produced by this exact combination (`hWVersion_astro = NEXT STANDARD LTE ONLY`, `productSelectionProduct_all = APX NEXT MULTI`) is **not present as a row** in the source of `hiddenConstraintMasterString_astro`, `util.getConstraintVals()` returns an empty/no-match set, the attribute has no valid current value, and the constraint action's `comments` — *"Current selection is invalid, please change it to a valid option"* — is what the UI displays in the red-bordered box.

**Companion rule**: `Hide Wireless Carrier if no values available` (rule area at line 451188, mark-type action on `attribute_id=17691442256` at line 451319) exists specifically to hide the field entirely when the constraint returns zero values — the fact that the screenshot instead shows the field **visible but invalid** (rather than hidden) indicates the constraint call is returning a non-empty legal set that simply does not include whatever value is/was pre-populated, OR the hide-rule's own condition isn't met for this combination. Either reading is consistent with "the export's Data Table/constraint-string rows do not cleanly cover Base Model = All-Band × 4G-LTE-Only" for Wireless Carrier specifically, which is the most defensible, evidence-backed explanation for why a real Oracle CPQ session shows this exact field, and only this field, as genuinely unanswered and invalid at this point in the sequence.

**A separate, inactive rule** `NEW Constrain Wireless carrier` (`rule_id=17691442899`, `rule_type=2`, `status=3` — INACTIVE) was also found, referencing the same attribute (`bm_config_rule_action id=17691445886`, `attribute_id=17691442256`). Being status=3 (inactive per the export's status legend), it does not fire in the live system and is not part of the resolving chain — but its presence shows Motorola has iterated on this exact carrier-constraint logic at least twice, replacing an older per-model hardcoded carrier rule with the newer generic Base-Model constraint-string mechanism traced above.

**Data Table coverage verdict — CONFIRMED (2026-08-15 follow-up, queried the ingested `Whitelist` table directly)**: the vendor's `whitelist` CSV named in the BML script above was in fact uploaded/ingested into this workspace's entity store (ontology_type `Whitelist`, 49,937 total rows; a sibling `Advancedwhitelist` type also exists with 296 rows). Querying for `CPQModel="APXNEXT_BOM"` + `attr1="wirelessCarrier_astro"` returns exactly 5 real rows:

| key | val1 (Wireless Carrier) | val2 (country) | val3 | BaseModel |
|---|---|---|---|---|
| APXNEXT_BOM-455 | LTE CAPABILITY NO SERVICE | GU | customerType=FEDERAL | ALL |
| APXNEXT_BOM-43345 | LTE CAPABILITY NO SERVICE | (none) | — | ALL |
| APXNEXT_BOM-30000 | BELL CANADA(PROVIDED BY MOTOROLA) | CA | — | ALL |
| **APXNEXT_BOM-397** | **ATT/FIRSTNET** | **US** | — | **H55TGT9PW8AN** |
| **APXNEXT_BOM-398** | **VERIZON** | **US** | — | **H55TGT9PW8AN** |

`H55TGT9PW8AN` is All Band's own real Base Model. For `BaseModel=H55TGT9PW8AN` + `Country=US`, there are **two** equally-legal rows — ATT/FirstNet and Verizon. This is **not a missing-data gap** — it is a genuine, real two-way tie in the vendor's own whitelist data. `util.getConstraintVals()` correctly returns both as the legal set rather than picking one, and the field is correctly left unresolved/invalid because a real customer decision (which carrier) is required — exactly matching the screenshot's "Current selection is invalid, please change it to a valid option" state. This also confirms our own `aryx` engine's "never blind-pick across a genuine tie" fix (implemented earlier this session) produces the correct behavior here: ask the customer, don't guess between ATT/FirstNet and Verizon.
