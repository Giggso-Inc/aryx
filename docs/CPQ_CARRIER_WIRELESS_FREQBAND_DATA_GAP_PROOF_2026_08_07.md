# Proof: Carrier Selection / Wireless Carrier / Frequency Band (MSL) resolution gap is a DATA issue, not an Aryx code issue

**Date:** 2026-08-07
**Scope:** `carrierSelectionMultiSelect_astro`, `wirelessCarrier_astro`, `modelSelectionFrequencyBandMsl_astro` — APX NEXT / ASTRO Devices_BOM
**Source of truth:** `APXNext_CnofigData.xml` (raw Oracle CPQ export), cross-checked against the live "Menu Attribute Editor: Carrier Selection → Related Rules" screenshots (Constraint list + Hiding Attribute list), and against a real ingestion run of the raw XML into a fresh Aryx workspace (`workspace_id=36`, this session).
**Explicitly not a fix.** No code was changed to produce this document. It is a diagnostic record only.

---

## 0. How to read this document

Each of the three attributes gets its own section with the same five parts:

1. **Rule inventory** — every rule that governs the attribute, cross-checked against the screenshot.
2. **Call chain** — which rule calls which BML platform function, in order.
3. **Full BML script** — the actual code, unedited.
4. **What's missing in the XML** — the exact field, proven empty.
5. **Verdict** — data issue or code issue, and whether re-ingesting by catalog hierarchy (Product Family → Product Line → Model) instead of flat rule lookup would change the answer.

A dedicated §4 explains the two platform functions (`util.getConstraintVals`, `util.getDefaultValues`) mechanically, since both attributes' resolution funnels through them. §5 is the empirical proof from actually running the ingestion. §6 is the final verdict table.

---

## 1. Carrier Selection (`carrierSelectionMultiSelect_astro`, attribute id `18302531460`)

### 1.1 Rule inventory (matches the screenshot exactly)

| Label | Level | Rule Type | Status | Order |
|---|---|---|---|---|
| Restrict Attribute Values Based on Model & Base Model (Portable) | Product Line (ASTRO Devices_BOM) | Constraint | Active | 1 |
| Do not allow Tmobile satellite with specific smartapps | Model (APX NEXT) | Constraint | Active | 91 |
| Force VERIZON carrier selection | Model (APX NEXT) | Constraint | Active | 103 |
| Minimum 2 SIMs for dual active SIM error message | Model (APX NEXT) | Constraint | Active | 104 |
| Constrain Carrier Selection Maximum Based on Dual Sim Toggle | Model (APX NEXT) | Constraint | Active | 101 |
| INACTIVE Require 1 additional sim if dual sim enabled | Model (APX NEXT) | Constraint | **Inactive** (status=3) | 102 |
| Hide Carrier Selection if no values available (portables) | Product Line (ASTRO Devices_BOM) | Hiding Attribute | Active | 111 |

This is the complete set from both attached screenshots — 6 Constraint rules + 1 Hiding rule. No rule outside this list touches `carrierSelectionMultiSelect_astro`.

### 1.2 Call chain

```
Turn starts
   │
   ▼
[Hide Carrier Selection if no values available (portables)]   (decides: shown at all?)
   │  script: SPLIT(hiddenMasterStringForAstroPortable_astro, recSep)
   │          → findinarray(..., "carrierSelectionMultiSelect_astro")
   │  BLOCKED HERE — see §1.4
   ▼
[Restrict Attribute Values Based on Model & Base Model (Portable)]   (decides: which options are legal?)
   │  script: util.getConstraintVals(inputParam, filterCriteria)
   │          inputParam["Constrain Master String"] = hiddenConstraintMasterString_astro
   │  BLOCKED HERE TOO — see §1.4
   ▼
[Do not allow Tmobile satellite ...] → session-side-effect DISALLOW (needs TE_FLAG session var)
[Force VERIZON carrier selection]    → session-side-effect ALLOW    (needs sessionVariable_TER)
[Minimum 2 SIMs ...]                 → pure logic on already-filled attrs, no external data needed
[Constrain Carrier Selection Max...] → pure logic on already-filled attrs, no external data needed
[INACTIVE Require 1 additional sim]  → status=3, never fires
```

The two rules at the top of the chain are the ones that decide (a) whether the attribute is shown at all, and (b) which values are legal — both are blocked on missing data. The rest are downstream refinements that only matter once (a) and (b) have resolved.

### 1.3 Full BML scripts

**Hide Carrier Selection if no values available (portables)** — condition script (`bm_function` id `18374451646`):
```bml
splitstringArray = SPLIT(hiddenMasterStringForAstroPortable_astro,hidddenRecordSeparator_allFamilly);
valindex         = findinarray(splitstringArray,"carrierSelectionMultiSelect_astro");

if(valindex ==-1){
 return TRUE;
}
else{
 if(modelSelectionbaseModel_astro==""){
  return TRUE;
 }     
}

return FALSE;
```
Hide targets (via `bm_config_marked_attr`, `mark_type=3`): **both** `carrierSelectionMultiSelect_astro` AND `selectSecondarySIMCard_astro` — one rule controls two attributes.

**Restrict Attribute Values Based on Model & Base Model (Portable)** — the Carrier Selection action inside the 55-action mega-rule:
```bml
filterCriteria = string[];
inputParam     = dict("string");

put(inputParam,"Constrain Master String",hiddenConstraintMasterString_astro);
put(inputParam,"recSep",hiddenRowSeparator_allFamily);
put(inputParam,"rowSep",hidddenRecordSeparator_allFamilly);
put(inputParam,"Base Model",modelSelectionbaseModel_astro);
put(inputParam,"Attribute Variable Name","carrierSelectionMultiSelect_astro");
put(inputParam,"Attribute UI Sequence",hiddenUISequenceMasterString_astro);

//Geography
if(not isnull(modelSelectionRegion_astro) AND modelSelectionRegion_astro<>"" AND modelSelectionRegion_astro<>" "){
   append(filterCriteria,"modelSelectionRegion_astro");
   append(filterCriteria,modelSelectionRegion_astro);
} 
if(not isnull(ultimateDestinationCountry) AND ultimateDestinationCountry<>"" AND ultimateDestinationCountry<>" "){
   append(filterCriteria,"ultimateDestinationCountry");
   append(filterCriteria,ultimateDestinationCountry);
} 
if(not isnull(productSelectionProduct_all) AND productSelectionProduct_all<>"" AND productSelectionProduct_all<>" "){
   append(filterCriteria,"productSelectionProduct_all");
   append(filterCriteria,productSelectionProduct_all);
} 
if(not isnull(aTAKEnabledPackage_astro) AND aTAKEnabledPackage_astro<>"" AND aTAKEnabledPackage_astro<>" "){
   append(filterCriteria,"aTAKEnabledPackage_astro");
   append(filterCriteria,aTAKEnabledPackage_astro);
} 
if(not isnull(applicationServicesSelection_astro) AND applicationServicesSelection_astro<>"" AND applicationServicesSelection_astro<>" "){
   append(filterCriteria,"applicationServicesSelection_astro");
   append(filterCriteria,applicationServicesSelection_astro);
}
if(not isnull(carrierSelectionMultiSelect_astro) AND carrierSelectionMultiSelect_astro<>"" AND carrierSelectionMultiSelect_astro<>" "){
   append(filterCriteria,"carrierSelectionMultiSelect_astro");
   append(filterCriteria,carrierSelectionMultiSelect_astro);
}
//calling functon and returning user selectable attributes
return util.getConstraintVals(inputParam, filterCriteria);
```
Note the self-referential last filter key: the rule filters on the attribute's *own current value* as part of computing its *next* set of legal values.

**Force VERIZON carrier selection** — condition `1 AND 2 AND 3 AND 4` (Base Model==`H55TGT9PW8BN`, Dual Active Sim==`true`, Carrier Selection does-not-contain `VERIZON`, ConstraintMasterString<>`''`), action:
```bml
retVal = "VERIZON";
if(sessionVariable_TER <> ""){
  setValResp = util.setConstraintValuesInSession("carrierSelectionMultiSelect_astro", retVal, "ALLOW" +"_"+ sessionVariable_TER);
}
return retVal;
```

**Do not allow Tmobile satellite with specific smartapps** — condition `1 AND ((2 AND (3 OR 4 OR 5 OR 6)) OR 7)`, action:
```bml
retVal = "T MOBILE AND T SATELLITE";
if(not isnull(usersessionget("TE_FLAG"))) {
  setValResp = util.setConstraintValuesInSession("carrierSelectionMultiSelect_astro", retVal, "DISALLOW");
}
return retVal;
```

### 1.4 What's missing in the XML

Two runtime lookup tables are referenced, and both are **confirmed empty** in every one of the 15 language variants of their `default_value`:

| Master string variable | Referenced by | `default_value` in XML |
|---|---|---|
| `hiddenMasterStringForAstroPortable_astro` | Hiding rule (which attribute applies to this base model) | `""` (empty, all 15 locales) |
| `hiddenConstraintMasterString_astro` | Value-restriction rule (`util.getConstraintVals`) | `""` (empty, all 15 locales) |

Both are `hidden=1` system attributes — populated by Oracle CPQ **at runtime**, not shipped in a static rule export. Confirmed exhaustively (§5) — not just for these two, but for every `*MasterString*`-named attribute in the file (11 total, all empty).

### 1.5 Verdict — data or code, and does catalog hierarchy help?

**Data issue.** The rule logic is complete, internally consistent, and (per §5) ingests into Aryx byte-for-byte correctly. There is nothing for the code to compute — `SPLIT("", sep)` and `util.getConstraintVals(...)` with an empty master string both have a well-defined *empty* answer, not a wrong one; the answer is empty because the input is empty.

**Would going up the Product Family → Product Line → Model hierarchy fix it?** No. The rule that needs the data is scoped at **Product Line** level (`ASTRO Devices_BOM`) already — one level *above* the Model (`APX NEXT`) — so it already sees everything the Model level would. The master string isn't scoped at a *higher* catalog level we failed to check; it's scoped at **runtime/session level**, populated by a mechanism outside the catalog hierarchy entirely (most likely a per-quote or per-session data sync, the same class of source as the `bmql("SELECT ... FROM Oracle_BomItemMap ...")` query that resolves Base Model — see the earlier base-model finding in this session's history). Re-organizing the ingestion by catalog level cannot surface data that was never exported at *any* catalog level.

---

## 2. Wireless Carrier (`wirelessCarrier_astro`, attribute id `17691442256`)

### 2.1 Rule inventory

| Label | Rule Type | Status | Order |
|---|---|---|---|
| Restrict Attribute Values Based on Model & Base Model (Portable) *(same mega-rule as §1, separate action)* | Constraint | Active | 1 |
| Force Set Wireless Carrier="LTE CAPABILITY NO SERVICE" when ATAK is enabled | Recommendation | Active | 10 |
| Restrict NONE for wireless carrier unless DELETE LTE and US | Constraint | Active | 7 |
| *("System recommendation" default-value rule #1 — sets default per base model)* | Recommendation | Active | — |
| *("System recommendation" default-value rule #2 — CA-only override)* | Recommendation | Active | — |
| *(Constraint: "LTE CAPABILITY NO SERVICE" via TE_FLAG session, ALLOW)* | Constraint | Active | — |
| *(Constraint: retVal="" via TE_FLAG session, DISALLOW — commented duplicate inline)* | Constraint | Active | — |
| NEW Constrain Wireless carrier | Constraint | **Inactive** (status=3) | — |
| Hide Wireless Carrier if no values available | Hiding Attribute | Active | — |

(Rows in *italics* are the same script family as the two "System recommendation" scripts quoted in full below; both are real, separate `bm_config_rule_action` entries. This attribute has 7 rule-action references total, plus 1 hiding rule — more than Carrier Selection, but built from the identical two idioms.)

### 2.2 Call chain

```
Turn starts
   │
   ▼
[Hide Wireless Carrier if no values available]      (shown at all?)
   │  SPLIT(hiddenMasterStringForAstroPortable_astro, recSep) → findinarray(..., "wirelessCarrier_astro")
   │  BLOCKED — same master string as §1, still empty
   ▼
[Restrict Attribute Values Based on Model & Base Model (Portable)]   (which options legal?)
   │  util.getConstraintVals(...) keyed on hiddenConstraintMasterString_astro
   │  BLOCKED — same table as §1
   ▼
["System recommendation" default-value rule #1]   (what's the DEFAULT value?)
   │  if FEDERAL+ATAK or INTL-FED product → literal "LTE CAPABILITY NO SERVICE"
   │  elif destination==CA               → literal "BELL CANADA(PROVIDED BY MOTOROLA)"
   │  else                                → util.getDefaultValues(inputParam)
   │                                         BLOCKED — keyed on defaultAttrValuesMasterString_astro
   ▼
[Force Set Wireless Carrier... when ATAK enabled]   → simple, no master-string dependency (fires independently)
[Restrict NONE for wireless carrier unless...]      → session-side-effect, no master-string dependency
```

### 2.3 Full BML scripts

**Hide Wireless Carrier if no values available** — condition script (`bm_function` id `17691441893`):
```bml
splitstringArray = SPLIT(hiddenMasterStringForAstroPortable_astro,hidddenRecordSeparator_allFamilly);
valindex         = findinarray(splitstringArray,"wirelessCarrier_astro");

if(valindex ==-1){
 return TRUE;
}
else{
 if(modelSelectionbaseModel_astro==""){
  return TRUE;
 }     
}

return FALSE;
```
Mirror image of §1's hiding rule — same master string, different literal (`"wirelessCarrier_astro"` instead of `"carrierSelectionMultiSelect_astro"`). This is the mechanism that makes the two attributes mutually exclusive *in principle*: whichever literal the (missing) master string actually lists for a given base model determines which one shows. With the table empty, both rules independently evaluate `valindex==-1` → `TRUE` → **both would be hidden** if evaluated literally on this data (this is exactly why Aryx's new Idiom-D evaluator, added earlier this session, reports this case as *unknown*, not a confident hide — see §5).

**"System recommendation" default-value rule #1** (`bm_config_rule_action` id `17691446329`):
```bml
/** This rule will set default value for attribute — Ketki 06/29/21 Created **/

inputParam = dict("string");
cpqModel   = upper(_bm_model_variable_name);
put(inputParam,"Attribute Variable Name","wirelessCarrier_astro");
put(inputparam,"Default Attribute Master String",defaultAttrValuesMasterString_astro);
put(inputParam,"rowSep",hiddenRowSeparator_allFamily);
put(inputParam,"recSep",hidddenRecordSeparator_allFamilly);
put(inputParam,"baseModel",modelSelectionbaseModel_astro);
put(inputParam,"Item Type","S");
put(inputParam,"basemodelattribname","modelSelectionbaseModel_astro");
put(inputParam,"model",cpqModel);

if (((customerType=="FEDERAL") AND (aTAKEnabledPackage_astro=="YES")) OR (productSelectionProduct_all=="APX NEXT INTL FED")){
	return "LTE CAPABILITY NO SERVICE";
}
elif (ultimateDestinationCountry=="CA"){
	return "BELL CANADA(PROVIDED BY MOTOROLA)";
}

//calling function and returning value
return util.getDefaultValues(inputParam);
```

**"System recommendation" default-value rule #2** (`bm_config_rule_action` id `18654807727`) — same shape, CA-only fallback, no FEDERAL/ATAK branch:
```bml
inputParam = dict("string");
cpqModel   = upper(_bm_model_variable_name);
put(inputParam,"Attribute Variable Name","wirelessCarrier_astro");
put(inputparam,"Default Attribute Master String",defaultAttrValuesMasterString_astro);
put(inputParam,"rowSep",hiddenRowSeparator_allFamily);
put(inputParam,"recSep",hidddenRecordSeparator_allFamilly);
put(inputParam,"baseModel",modelSelectionbaseModel_astro);
put(inputParam,"basemodelattribname","modelSelectionbaseModel_astro");
put(inputParam,"model",cpqModel);

if ((ultimateDestinationCountry=="CA")){
	return "BELL CANADA(PROVIDED BY MOTOROLA)";
}

return util.getDefaultValues(inputParam);
```

**Restrict NONE for wireless carrier unless DELETE LTE and US** — condition `1 AND 2 AND 3` (`Delete LTE Capability` <> `"YES"`, `Ultimate Destination Country` == `"PR~US~VI"`, `Base Model` <> `""`):
```bml
retVal = "";
/*
if(not isnull(usersessionget("TE_FLAG"))) {
  setValResp = util.setConstraintValuesInSession("wirelessCarrier_astro", retVal, "DISALLOW");
}
*/

if(not isnull(usersessionget("TE_FLAG"))) {
  setValResp = util.setConstraintValuesInSession("wirelessCarrier_astro", retVal, "DISALLOW");
}

return retVal;
```
(The commented-out block duplicated verbatim below it, uncommented — a leftover from editing, not a logic bug worth chasing.)

**Force Set Wireless Carrier="LTE CAPABILITY NO SERVICE" when ATAK is enabled** — condition `1` (`ATAK Enabled Package` == `"YES"`), single input, no script body captured (direct constant action) — fires independently of any master string.

### 2.4 What's missing in the XML

Same two tables as §1, plus a third:

| Master string variable | Referenced by | `default_value` in XML |
|---|---|---|
| `hiddenMasterStringForAstroPortable_astro` | Hiding rule | `""` (empty) |
| `hiddenConstraintMasterString_astro` | Value-restriction rule | `""` (empty) |
| `defaultAttrValuesMasterString_astro` | Both "System recommendation" default-value rules, via `util.getDefaultValues` | `""` (empty) |

### 2.5 Verdict

**Data issue**, same reasoning as §1.2's verdict, plus one nuance: this attribute's default-value rules have a **partial, literal fallback path** (the FEDERAL+ATAK / CA branches) that *is* fully resolvable today with zero missing data — those two conditions never touch a master string at all. Only the *general* case (neither FEDERAL+ATAK nor Canada) falls through to `util.getDefaultValues`, which is blocked. So for those two specific business conditions, the code can and does produce a correct, deterministic answer right now; the gap is scoped to "everything else," not the whole attribute.

Catalog-hierarchy re-scoping doesn't help here either, for the identical reason as §1.5 — `defaultAttrValuesMasterString_astro` is `hidden=1`/runtime-populated, not exported at Model, Product Line, or Product Family level.

---

## 3. `modelSelectionFrequencyBandMsl_astro` (attribute id `17691442132`)

### 3.1 Rule inventory

| Label | Rule Type | Status | Depends on missing data? |
|---|---|---|---|
| Restrict Attribute Values Based on Model & Base Model (Portable) *(same mega-rule, separate action)* | Constraint | Active | **Yes** — `util.getConstraintVals` |
| Hide Frequency Band Model Selection Attribute for APX NEXT All Band model | Hiding Attribute | Active | **No** — pure product-name logic |
| Hide Frequency Band for Single Band | Hiding Attribute | Active | **No** — pure product-name logic, but dead (see below) |
| Hide Frequency Band & Extend Range if Product is selected as APX Enhanced | Hiding Attribute | **Inactive** (status=3) | N/A — never fires |

### 3.2 Call chain

```
Turn starts
   │
   ▼
[Hide Frequency Band Model Selection Attribute for APX NEXT All Band model]
   │  if productSelectionProduct_all in {APX NEXT INTL FED, APX NEXT MULTI, APX NEXT XE MULTI,
   │                                      APX NEXT INTL, APX NEXT XN ALL} → hide
   │  RESOLVES CORRECTLY — no missing data, proven for all 10 real product values (§3.4)
   ▼
[Hide Frequency Band for Single Band]
   │  if productSelectionProduct_all == "APX NEXT SINGLE" → hide
   │  DEAD RULE — no real option is literally "APX NEXT SINGLE" (all 3 single-band options
   │  are "...SINGLE BAND"). Never fires. A pre-existing catalog typo, not a runtime-data gap.
   ▼
[Restrict Attribute Values Based on Model & Base Model (Portable)]   (which specific band values legal?)
   │  util.getConstraintVals(inputParam, filterCriteria) keyed on hiddenConstraintMasterString_astro
   │  BLOCKED — same table as §1/§2
```

### 3.3 Full BML scripts

**Hide Frequency Band Model Selection Attribute for APX NEXT All Band model** — condition script (`bm_function` id `17691441659`):
```bml
//  07/25/2025    Sivasree : To hide the Frequency Band based on the product selected

if( ((productSelectionProduct_all=="APX NEXT INTL FED") OR (productSelectionProduct_all=="APX NEXT MULTI") OR (productSelectionProduct_all=="APX NEXT XE MULTI") OR (productSelectionProduct_all=="APX NEXT INTL") OR (productSelectionProduct_all=="APX NEXT XN ALL"))){
	return true;
}
return false;
```

**Hide Frequency Band for Single Band** — condition type 1 (declarative, not script), single input: `Product (productSelectionProduct_all)` **==** `"APX NEXT SINGLE"`. No real menu option equals this literal string.

**Restrict Attribute Values Based on Model & Base Model (Portable)** — the Frequency Band MSL action inside the mega-rule (abridged — full filter-criteria list is ~25 attributes; the load-bearing lines):
```bml
/** Shreyas 03/14/16 Created; Shreyas 03/14/16 Added Frequency Band Msl for APX8000/XE **/

filterCriteria = string[];
inputParam     = dict("string");

put(inputParam,"Constrain Master String",hiddenConstraintMasterString_astro);
put(inputParam,"recSep",hiddenRowSeparator_allFamily);
put(inputParam,"rowSep",hidddenRecordSeparator_allFamilly);
put(inputParam,"Base Model",modelSelectionbaseModel_astro);
put(inputParam,"Attribute Variable Name","modelSelectionFrequencyBandMsl_astro");
put(inputParam,"Attribute UI Sequence",hiddenUISequenceMasterString_astro);

... (Geography, Product, Frequency Bands, Keypad/Display/Knob type, Submersible,
     Housing, Hazardous Location, Made-in-America, self-referential
     modelSelectionFrequencyBandMsl_astro, customerType/UIN, RFID, Operation Mode,
     System Enhancement, Advanced System Key, Secure/Multikey, Antenna, Battery,
     Cable, Belt Clip, Package Type, Documentation, Manual, Service Type/Duration —
     ~25 filter keys total, same append(filterCriteria, key); append(filterCriteria, value) pattern) ...

//calling functon and returning user selectable attributes
return util.getConstraintVals(inputParam, filterCriteria);
```

### 3.4 Empirically proven correct (the hiding half)

Unlike §1 and §2's hiding rules, this one has **no nested-if / no master-string dependency** — it's plain `if/OR/return true|false`. I ran it through Aryx's real `evaluate_hide_tier1()` (the exact function `apply_hiding_rules` calls in production) for all 10 relevant product values earlier this session:

| Product | `hide` |
|---|---|
| APX NEXT SINGLE BAND / XE SINGLE BAND / XN SINGLE BAND | `False` |
| APX NEXT ENHANCED / XE 4G LTE PLUS 5G (5G-only products) | `False` |
| APX NEXT INTL FED / MULTI / XE MULTI / INTL / XN ALL | `True` |

All 10 matched the rule's intent exactly, `blocked_by_missing_var=False` in every case — full deterministic Tier-1 resolution, zero data gap for **whether the field shows**.

### 3.5 What's missing in the XML

| Master string variable | Referenced by | `default_value` in XML |
|---|---|---|
| `hiddenConstraintMasterString_astro` | Value-restriction rule (`util.getConstraintVals`) | `""` (empty) |

Only one table this time, and it only affects **which specific band values are legal** — not whether the field is shown at all (that part is fully solved, §3.4).

### 3.6 Verdict

**Split verdict — mostly a non-issue, with one confirmed data gap.**
- Show/hide: **fully correct today**, zero code or data issue.
- The dead "Hide Frequency Band for Single Band" rule: a **pre-existing catalog authoring bug** (typo'd literal), not a data-availability issue — harmless here because the outcome it would have produced (don't hide) already happens by default without it.
- Which specific values are legal: **data issue**, identical root cause and identical non-answer from catalog-hierarchy re-scoping as §1.5.

---

## 4. How `util.getConstraintVals` / `util.getDefaultValues` actually work — and why re-reading the XML can never recover them

**Correction (2026-08-07, later same session):** the opening claim below — "not BML you can read the source of" — was wrong and is superseded by §7. `APX_util_library.xml` does contain a full, readable `script_text` body for both functions (`bm_lib_func` id `39185090`/`39184884`, `ref_type=16`, alongside a `java_class_name` pointing at a compiled counterpart — a documented BML implementation kept in parallel with a native one). The algorithm itself was fully recoverable from the export all along. What was **never** recoverable from any static export is the *data* the algorithm reads — see §7 for the direct, file-level proof, and §8 for how that gap was subsequently closed for one base model.

Every script that calls either function is client code building an *input*, then handing off:

```
inputParam = dict("string")
put(inputParam, "Constrain Master String" | "Default Attribute Master String", <the master-string attribute>)
put(inputParam, "recSep", hidddenRecordSeparator_allFamilly)     ← record delimiter
put(inputParam, "rowSep", hiddenRowSeparator_allFamily)          ← row delimiter
put(inputParam, "Base Model", modelSelectionbaseModel_astro)     ← lookup key
put(inputParam, "Attribute Variable Name", "<this attribute>")   ← which column to return
filterCriteria = [key1, value1, key2, value2, ...]               ← extra WHERE-clause-like filters
return util.getConstraintVals(inputParam, filterCriteria)        ← or util.getDefaultValues(inputParam)
```

Conceptually this is Oracle CPQ running the equivalent of:
```sql
SELECT <Attribute Variable Name>
FROM   <the master-string table, encoded as one giant delimited string>
WHERE  BaseModel = <modelSelectionbaseModel_astro>
  AND  <each filterCriteria key/value pair>
```
— except the "table" is the literal *value* of an attribute like `hiddenConstraintMasterString_astro`, encoded as `record` × `row` × `field` using the three delimiter variables passed in (`recSep`/`rowSep` plus an implicit field separator). Both `recSep`/`rowSep` variable names are consistently `hidddenRecordSeparator_allFamilly` (note the triple-d typo, verbatim in every script) and `hiddenRowSeparator_allFamily` across all ~55+ rules that use this pattern — confirming one shared encoding convention across the whole catalog, not per-rule variation.

**Why the XML export can never contain the answer, no matter how it's read:** the master-string attribute's *value* is what Oracle CPQ's runtime populates from an external source (most likely a synced Item Master / pricing table, given the "BOM Mapping table" comment found on the Base Model resolution rule: `bmql("SELECT ... FROM Oracle_BomItemMap ...")`). A rules/attributes XML export captures the **catalog definition** (attributes, rules, scripts, menu options) — it does not, and structurally cannot, capture **live database table contents** that a script merely references by name. This is true regardless of hierarchy level (Model/Product Line/Product Family all inherit the same empty attribute), regardless of parser sophistication (a perfect BML interpreter still has nothing to query), and regardless of which tool reads the file (confirmed identically via raw regex AND via Aryx's real XML→entity ingestion — see §5).

---

## 5. Empirical proof (not just static analysis)

To rule out "maybe the file has it and the analysis missed it," this session:

1. **Exhaustively searched the whole 28MB file** for the actual table data: all 11 `*MasterString*`-named attributes (all empty), the one `<data>` blob on the root element (a corrupted Java `byte[].toString()` — `[B@52e1d946` — not recoverable text), every non-script CDATA block over 2KB in the entire file (all `flow_template` HTML/CSS, unrelated), and every tag name containing table/lookup/price/data/cache/blob/constraint/master (`system_config_metadata` ×2990 all empty, `property_data_table`/`property_data_source` ×430 empty, `layout_data` ×8 empty).

2. **Ran the raw XML through Aryx's real ingestion pipeline** into a fresh workspace (`workspace_id=36`, `/admin/ingest/file`) and queried the resulting `aryx_entity` rows directly via the `/data/entities` API:
   - `BmConfigRule`: **714/714** ingested — full fidelity, no truncation.
   - `BmConfigAttr`: **430/430** ingested — full fidelity.
   - Spot-checked "Force VERIZON carrier selection" (id `18654807104`) in the ingested data — field-for-field identical to the raw XML.
   - `hiddenConstraintMasterString_astro`, `hiddenMasterStringForAstroPortable_astro`, `defaultAttrValuesMasterString_astro` all ingested with `hidden="1"`, **`default_value: None`** — confirmed empty in Aryx's own data, not an artifact of manual analysis.
   - `carrierSelectionMultiSelect_astro`, `wirelessCarrier_astro`, `modelSelectionFrequencyBandMsl_astro` all ingested correctly as real, addressable attributes.

3. **Confirmed the storage/query seam has no bug**: `PostgresCpqRdb` (`src/aryx/cpq/rdb.py`) normalizes `ontology_type` via `replace(lower(ontology_type),'_','') LIKE '%bmconfigrule'` — correctly bridges the ingestion pipeline's `BmConfigRule` naming to what `CpqEngine` queries for. No case/naming mismatch anywhere in the pipeline.

4. **Ran the actual production BML evaluator** (`bml.py::evaluate_hide_tier1`) against the real hiding-rule scripts for all three attributes, with and without the master-string data present, confirming: (a) §3's hiding rule resolves deterministically and correctly with zero data dependency, (b) §1/§2's hiding rules structurally cannot resolve without the master string — not because of a parser gap (that nested-if grammar gap was found and fixed separately this session), but because an empty master string is a legitimate "unknown," not a wrong answer.

---

## 6. Final verdict table

| Attribute | Show/hide resolvable today? | Which-value resolvable today? | Root cause | Fixable by re-ingesting at a different catalog level? |
|---|---|---|---|---|
| `carrierSelectionMultiSelect_astro` | No — blocked on `hiddenMasterStringForAstroPortable_astro` | No — blocked on `hiddenConstraintMasterString_astro` | **Data** (both tables empty in export; runtime-populated) | **No** — not a hierarchy-scoping problem, tables aren't exported at *any* level |
| `wirelessCarrier_astro` | No — blocked on same table as above | Partial — 2 literal business-rule branches resolve correctly; general case blocked on `defaultAttrValuesMasterString_astro` | **Data**, with a real partial code-resolvable path | **No**, same reasoning |
| `modelSelectionFrequencyBandMsl_astro` | **Yes** — fully correct, proven for all 10 product values | No — blocked on `hiddenConstraintMasterString_astro` | Show/hide: none. Which-value: **Data**. One unrelated dead rule (catalog typo, harmless) | **No** for the which-value half; show/hide already needs no fix |

**One real Aryx code gap was found and already fixed this session** (stashed, not yet re-applied): `bml.py`'s Tier-1 parser couldn't recognize the nested-if "hide unless in master list AND base model set" grammar shape used by §1/§2's hiding rules — independent of the data problem, and only matters once the real master-string data becomes available. It does not change any verdict in the table above.

**Bottom line (original, static-export-only scope):** getting these three attributes to resolve correctly requires a live/admin export of the actual resolved master-string values (`hiddenConstraintMasterString_astro`, `hiddenMasterStringForAstroPortable_astro`, `defaultAttrValuesMasterString_astro`) — and, for Base Model itself, the `Oracle_BomItemMap` table — from whoever administers this Oracle CPQ catalog. No amount of Aryx code work, and no re-ingestion strategy by catalog hierarchy, can substitute for data that was never present in the source export.

See §8 — this was subsequently obtained (Pipeline Viewer capture) and wired into Aryx for one base model. The static-export limitation above still holds for every other base model.

---

## 7. Re-confirmation against the two source files directly (same session, later pass)

Prompted by a follow-up question — "why the utils files and XML aren't enough to solve this" — both files were re-checked directly rather than from memory, since a memory of a file's contents is a claim about the past, not the present.

**`APX_util_library.xml`** (8,493,421 bytes): `getConstraintVals` (`bm_lib_func` id `39185090`) and `getDefaultValues` (id `39184884`) both located. Each carries a `java_class_name` (`com.bm.xchange.bmscript.bmllib.util.LibFunction_get*_1`) **and** a full readable `script_text` — this is the file `master_string_algorithm.py` (§8) was ported from, confirmed by direct grep, not assumption.

**`APXNext_CnofigData.xml`** (28,583,780 bytes): re-grepped the `hiddenConstraintMasterString_astro` attribute definition directly:
```
<default_value><en><![CDATA[]]></en><de><![CDATA[]]></de> ... (all 15 locales empty)
```
Confirms §1.4/§2.4/§3.5 again, independently, from a second grep pass against the raw bytes.

**Conclusion, restated plainly:** the util-library file is the *recipe*; the config-data file defines the *shelf* (the attribute exists) but never stocks the *ingredient* (a populated value). That split — algorithm fully present, data structurally absent — is a property of what a "Download Configuration" catalog export captures (schema + rules), not a gap in either file individually. A third file of the same export type would not help; a different *kind* of export (live session state) is what closed it — see §8.

---

## 8. Post-proof update: the gap was closed for one base model (Pipeline Viewer capture)

After this proof was written, a **Pipeline Viewer** export (Oracle CPQ's live-session diagnostic tool, distinct from "Download Configuration") was supplied for base model `H55TGT9PW8AN`. Unlike every static export checked in §5/§7, it contains the actual **populated** values of `hiddenConstraintMasterString_astro`, `hiddenUISequenceMasterString_astro`, `defaultAttrValuesMasterString_astro`, and `hiddenMasterStringForAstroPortable_astro`.

Built on top of it, in this codebase:
- `src/aryx/cpq/master_string_algorithm.py` — the real `getConstraintVals`/`getDefaultValues` logic (per §7), ported to Python and validated field-for-field against this captured data.
- `src/aryx/cpq/data/apx_next_live_snapshot_2026_08_07.json` — the captured values themselves, with provenance (base model, product, capture date).
- `src/aryx/cpq/master_string_resolver.py` — ties the two together, returning `None` for any base model other than `H55TGT9PW8AN` (never a guess).
- Wired into `CpqEngine.auto_fill()` as the first-priority fallback, ahead of the narrower screenshot-confirmed table.

**Scope of the fix:** real, not inferred, data — but for exactly the one base model this capture covers. Every other base model still has no data source and correctly resolves to "unknown" rather than a guess, per §1–§6 above. Capturing another base model's Pipeline Viewer session and adding it to the snapshot file is the same, already-proven mechanism.

---

## 9. Why `auto_fill()` picking one eligible value can't substitute for the missing data — and what "no data" actually produces

Prompted by a follow-up: given a real live-session example (`docs/CPQ_LIVE_SESSION_CARRIER_FREQBAND_MISMATCH_BUG_REPORT_2026_08_07.md`) showing both `wirelessCarrier_astro` and `carrierSelectionMultiSelect_astro` populated with *different* carrier values in one real Oracle CPQ transaction — confirming this isn't confirming an Aryx bug (that screenshot/payload never touched Aryx's code at all), but raising a sharper question: why can't Aryx's own `auto_fill()` just pick a value and be done with it?

**Because auto-fill and sibling reconciliation are two different mechanisms:**
- `auto_fill()` resolves **one attribute** from **its own** legal-value set.
- The carrier conflict is **between two attributes**, each with an independent rule chain, each unaware of the other's existence. Auto-filling attribute A correctly does not stop attribute B's separate rule from also firing and writing a value. Preventing a double-fill needs a cross-attribute reconciliation step — a different mechanism than auto-fill (this session built one, `exclusive_sibling_family_exclusions`, then reverted it per a later instruction).

**Why the master-string data is structurally required, not optional context:**
- `hiddenMasterStringForAstroPortable_astro` is the *only* place that encodes "for base model X, only `wirelessCarrier_astro` applies, not `carrierSelectionMultiSelect_astro`" (or the reverse). No rule or script derives that division independently.
- `hiddenConstraintMasterString_astro` is the *only* place that encodes "for base model X + country + product, these specific values are legal." The rule is a query into this table — it computes nothing on its own.

**What actually happens with the data absent (confirmed behavior, not a guess):**
- The constraint function (`util.getConstraintVals`) gets an empty table → returns an empty/unknown result. Not a crash.
- The hiding function's `findinarray()` on an empty split → `-1` → a literal read says "hide"; Aryx's safer Idiom-D parser instead reports "unknown" rather than a confident hide.
- **Does the payload fail?** Not at the schema/HTTP level — all three attributes are `<required>0</required>` in the catalog (confirmed by direct grep, §7-style check), so a REST submission omitting them should be accepted. The failure is a **business-correctness** one instead: if both siblings get filled anyway (exactly what the live example shows), the result is a structurally valid but internally contradictory quote — wrong carrier/BOM data reaching downstream pricing and fulfillment, which is worse than an honest "unknown."

---

## 10. Full catalog-wide scope: every other attribute wired to the same missing data

§1–§3 covered exactly 3 attributes. This section answers the natural follow-up: **which other attributes in the catalog depend on the same empty master strings?** Found by pattern-matching every `bm_function` script in the newest config export (`APXNext_CnofigData (1).xml`, 37MB) for each script that reads `hiddenConstraintMasterString_astro`, `defaultAttrValuesMasterString_astro`, or `hiddenMasterStringForAstroPortable_astro`, then extracting the specific `"Attribute Variable Name"` (or `findinarray(...)` literal) each one resolves.

**97 unique attributes total** are wired to at least one of the three master strings — this is a catalog-wide gap, not a 3-attribute one.

| Mechanism | Master string | Attribute count |
|---|---|---|
| Value-restriction (`util.getConstraintVals`) | `hiddenConstraintMasterString_astro` | 60 |
| Default-value (`util.getDefaultValues`) | `defaultAttrValuesMasterString_astro` | 39 |
| Show/hide gating (`findinarray` on the split table) | `hiddenMasterStringForAstroPortable_astro` | 78 |

**Notable cross-reference:** `salesApprover_astro` and `technicalContactEmailAddress_astro` both appear in the hiding-rule list — very likely the same underlying mechanism behind the live "Internal constraint error... Sales Approver Email Address" banner documented in `docs/CPQ_LIVE_SESSION_CARRIER_FREQBAND_MISMATCH_BUG_REPORT_2026_08_07.md`. Same root cause, a different attribute, now with a direct real-world sighting.

**Full list of the 94 attributes beyond the 3 already covered in §1–§3** (`carrierSelectionMultiSelect_astro`, `wirelessCarrier_astro`, `modelSelectionFrequencyBandMsl_astro`):

```
aSTROSystemID_astro                              aTAKEnabledPackage_astro
aTAKNonPromoApplicationServices_astro             addVX650VideoWirelessRemoteSpeakerMicrophone_astro
additionalApplicationServicesMonths_astro         additionalApplicationServices_astro
additionalSystemEnhancementFeatureType_astro      advancedSystemKeyHardwareKey_astro
antennasType_astro                                applicationServicePromoHelptext_astro
applicationServicePromotionalDuration_astro       applicationServicesHelpText1_astro
applicationServicesIntroBundle_astro              applicationServicesSelection_astro
baselineReleaseSWHelpText_astro                   baselineReleaseSW_astro
batteryIncludeaSpare_astro                        batteryQuantityforSpares_astro
batteryType_astro                                 beltClipType_astro
cBPQRCode_astro                                   cableDataCable_astro
configurationType_astro                           dELETELTE_astro
dHSAssetTagLabel_astro                            dMSDurationYears_astro
deviceManagementTraining_astro                    documentationDataLinkManagerSoftwareCD_astro
documentationTestResultsRatedAudioPrintoutLabel_astro   eNDUSERMCN_astro
enableDualActiveSim_astro                         extendRangeTo762764MHz_astro
fedQRCode_astro                                   firstName_astro
fourOrMoreApplicationsDiscountHelptext_astro       includeAccidentalDamageAddDMSCoverage_astro
isFedRampRequired_astro                           isProvisioningRequiredInCloudEnv_astro
isThisASPARERadioAntenna_astro                     isThisASPARERadioBatt_astro
itemTypeVX650_astro                                languageLanguageType_astro
lastName_astro                                     manual_astro
modelSelectionFrequencyBandPlus_astro              modelSelectionHazardousLocation_astro
modelSelectionHousing_astro                        modelSelectionKnobType_astro
modelSelectionSubmersibleDeltaT_astro              modelSelectionmadeInAmerica
msEnableDualBandOperation_astro                    multikeyType_astro
numberOfSeats_astro                                operationModeType_astro
packageTypeBundles_astro                           packingPackageType_astro
preSalesEnggAcknowledgement_astro                  productSelectionHelptext_astro
productSelectionProduct_all                        promoApplicationServices_astro
qtyOf12pinInterfaceto10PinRFDCAdaptor_astro        qtyOfVX650RemoteSpeakerMic_astro
qtyOfXVN500RemoteSpeakerMic_astro                  rFIDRFIDEquipped_astro
rSMDMSDuration_astro                               rSMType_astro
radioCentralSmartprogrammingHelptext_astro         sIMCardSelection_astro
salesApprover_astro                                secureEncryptionType_astro
selectEndUserType_astro                            selectProvAgencySSPL_astro
selectSecondarySIMCard_astro                       serviceActivationDelay_astro
serviceBatteryRefreshService_astro                 serviceDuration_astro
serviceTypeAdditionalDMSCoverage_astro             serviceTypeRSM_astro
serviceType_astro                                  smartLocateHelpText_astro
smartMessagingHelpText_astro                       softwareBundlesBundleType_astro
solutionTypeDevices_astro                          solutionTypeDuration_astro
spSurveillancePackagesType_astro                   spSurveillancePackagesTypes_astro
subscriptionBillingAddDMSCoverage_astro            systemEnhancementFeatureType_astro
systemID_astro                                     tAACompliant_astro
technicalContactEmailAddress_astro                 trainTheTrainerTraining_astro
videoRSM_astro                                     viqiSmartappText_astro
```

**Caveats on this list:**
- Derived by pattern-matching each rule's own `script_text` (what lookup key it puts before calling `util.getConstraintVals`/`getDefaultValues`, or what literal it searches for via `findinarray`) — it identifies which attributes are *wired* to the missing data, not whether each one has a partial literal fallback (like Wireless Carrier's FEDERAL/CA branches, §2.5) worth checking individually before assuming full blockage.
- `hiddenMasterStringForAstroPortable_astro`'s own direct `util.getConstraintVals`/`getDefaultValues` usage returned 0 matches — it is exclusively consumed via the `findinarray`/hiding-rule pattern (§1.3/§2.2), not the constraint/default-value pattern used by the other two master strings.
- This is the same root cause as §1–§9 applied catalog-wide — no new mechanism, no new fix required beyond what's already documented; this section exists to size the blast radius accurately rather than leave it implied.

**Superseded by §11 below.** The conclusion above — that no static export contains this data — was correct for every export type checked *at the time it was written*. §11 documents two Oracle CPQ **Data Table** exports (a different export type, not Rules/Attributes) that DO contain the real underlying source data for these master strings, catalog-wide.

---

## 11. The actual source tables, found: two Oracle CPQ Data Table exports close this gap completely

After §10 was written, two Data Table exports were supplied and checked directly against real data — not the narrow single-base-model Pipeline Viewer capture (§8), but the full catalog-wide source tables Oracle CPQ itself builds the master strings from.

### 11.1 `whitelist.csv` — source of `hiddenConstraintMasterString_astro`

**49,942 rows**, columns: `CPQModel, BaseModel, attr1/val1 ... attr8/val8` (up to 4 attribute/value filter pairs per row, plus optional `startDate`/`endDate`/audit columns). Each row is one `(attribute, legal value, filter conditions)` record — exactly the structure `util.getConstraintVals` parses out of the serialized master string.

**Verified against three independent sources, all in exact agreement:**
- **5,008 APX NEXT rows** confirmed present.
- **`modelSelectionFrequencyBandMsl_astro` for `H55TGT9PW8AN`:** rows for `UHF`, `VHF`, `700/800 MHZ` — exact match to the §8 Pipeline Viewer capture.
- **`wirelessCarrier_astro` for `H55TGT9PW8AN` + US:** `ATT/FIRSTNET`, `VERIZON`, plus the identical unconditional fallback row (`BaseModel=ALL`, `wirelessCarrier_astro=LTE CAPABILITY NO SERVICE`, no filters) — exact match to §8.
- **`carrierSelectionMultiSelect_astro` for `H55TGT9PW8BN`:** all 6 rows (`ATT/FIRSTNET`, `T MOBILE`, `VERIZON`, `BELL CANADA(PROVIDED BY MOTOROLA)`, `T MOBILE AND T SATELLITE`, `LTE CAPABILITY NO SERVICE`) match field-for-field, condition-for-condition, against a real Oracle CPQ admin trace page's own `ConstraintMasterString` value for that exact base model/product — the strongest possible confirmation, since that trace page IS Oracle CPQ showing its own assembled master string.

### 11.2 `attrSequence.csv` — source of `hiddenMasterStringForAstroPortable_astro` (and the UI sequence string)

**46,881 rows**, columns: `CPQModel, BaseModel, AttrName, Seq, optionOrReqFlag`. This is precisely the table the `hiddenMasterStringForAstroPortable_astro` setter rule (§ "Set Hidden Master String For Astro Portable", function id `17691441720` — a fully readable BML script, not compiled Java) queries via:
```
BMQL("SELECT distinct AttrName FROM $attrSeqTableName WHERE CPQModel=$cpqModel and BaseModel=$modelSelectionbaseModel_astro")
```
where `attrSeqTableName` defaults to `"attrSequence"`.

**Verified — and this resolves the sibling question definitively, for BOTH base models now:**
- `H55TGT9PW8AN`: `wirelessCarrier_astro` present (Seq `315`, flag `R`); `carrierSelectionMultiSelect_astro` **absent**.
- `H55TGT9PW8BN`: the opposite — a real Oracle CPQ admin trace page's own `hiddenMasterStringForAstroPortable` value for this base model explicitly lists `carrierSelectionMultiSelect_astro`, matching what this table implies.
- `modelSelectionFrequencyBandMsl_astro` present for both base models checked (Seq `55`/`23` depending on model/product).

Different base models genuinely use different siblings — exactly the mechanism §1/§2's hiding rules assume, now confirmed with real, catalog-wide, static data instead of one live-session snapshot.

### 11.3 Revised conclusion

**The data gap is closed, catalog-wide, with two ordinary static exports — not just one base model.** What was missing all along was not the *data* itself (it was always sitting in these two Data Table objects) but knowing to request a **Data Table export** rather than a Rules/Attributes ("Download Configuration") export. Given `whitelist.csv` + `attrSequence.csv`:
- `hiddenConstraintMasterString_astro` can be reconstructed for any base model/product/geo combination present in `whitelist.csv` — i.e., the whole APX NEXT line, not one captured session.
- `hiddenMasterStringForAstroPortable_astro` can be reconstructed for any base model in `attrSequence.csv`, correctly resolving which sibling attribute (`wirelessCarrier_astro` vs `carrierSelectionMultiSelect_astro`) applies.
- The 97-attribute blast radius from §10 is now, in principle, fully resolvable — not just the 2 attributes spot-checked here.

**Practical implication:** `master_string_resolver.py` (§8), currently scoped to exactly one base model via a single JSON snapshot, can be rebuilt against these two full CSV tables instead — removing the single-base-model limitation entirely. Not yet implemented as of this writing; this section documents the data source, not a code change.
