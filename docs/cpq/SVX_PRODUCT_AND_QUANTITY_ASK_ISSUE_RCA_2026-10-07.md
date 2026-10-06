# SVX quote flow: Ask forces fields the real screen never shows (issue, RCA, fix needed), 2026-10-07

> **DOC CONTRACT**
>
> - **Purpose**: record why Ask, on an SVX quote, asks for `Product`, six mounting quantities and other fields the real SVX screen does not show, and what has to change. Analysis only; it lists no commits and no code changes.
> - **Status**: LIVING. Findings come from the dev log of 2026-10-06 (workspace 1214), the SVX XML, the SVX layout export, and the data-table CSVs. Anything not verified says so.
> - **Last updated**: 2026-10-07.
> - **Formatting**: bullets only.

---

## 1. Issue

- Request: "I need a quote for SVX for US" (workspace 1214, XML plus data tables plus the SVX layout uploaded).
- The real SVX screen ("Product Configuration" tab) asks for: destination country, Solution Type, Subscription Duration, Select Model, an optional mounting table (whole number, 0 or blank), then Recommended Configuration (spare battery, battery subscription, charger, service type, DMS duration).
- Ask asked, one per turn: the model, then **Product** (291 options across every family), then six mounting-quantity attributes. Before the layout upload it also asked `mountType`, `accessoriesSolutionSet` and `solutionFeature` (11 pending fields on turn 1; 8 after the upload).
- From turn 5 on, every reply says "configuration incomplete, N attributes still need your input" and keeps asking one field per turn (the log runs to turn 10).
- The customer typed the product name `videoSolutions_BOM` for Product. It is not one of the 291 options, so Ask re-listed them.
- Recommended Configuration was never reached.

## 2. Evidence (dev log, workspace 1214, 2026-10-06 19:58)

- Route: `quote`; 207 attributes loaded for the catalog prefix `Video SolutionSvx`.
- Turn 1 pending (8 fields): `modelSelectionSelectModel_viSoln`, `productSelectionProduct_all`, five `mountingType...Quantity_viSoln`, and the TEK-LOK quantity. After the model is chosen the TEK-LOK quantity drops out, matching the five rows on the real screen.
- Product decision trace, identical on every pass: `is_decision_attr: true`, 325 valid options, `MULTIPLE_OR_DECISION`, `ask_or_pending -> pending (FORCED_ASK_ANCHOR)`.
- `ask.recompute.loop ... "skip_always_ask_count": 0` on both turns.
- `ask.answer.branch` turns 5 to 10 use branch `turn_cap` (`MAX_TURNS = 5`).
- `ask.model.fallback_static` (`ARYX_ASK_MODEL_FALLBACK_STATIC`, `NO_TIER_RESULT`) fires on turn 1 with the fixed `APXNEXT` pair.

## 3. Root cause (RCA)

### 3.1 Product is force-asked by a hardcoded rule that runs before the layout
- `auto_fill_stages/governance_flags.py` marks an attribute `is_decision_attr` when its name contains `country`, `region`, `selectmodel` or `basemodel`, when it is a Hardware Version attribute, or when its exact variable name is `productSelectionProduct_all`.
- `auto_fill_stages/ask_or_pending.py` appends every decision attribute to pending ("Checked FIRST, ahead of ...") before the layout-visibility gate other attributes go through.
- The rule was written for APX NEXT: the Product list is shared across the whole catalog (325 options) and no rule narrows it, and an earlier first-option pick put "APX6500" into an APX NEXT quote. It applies to every catalog by default.
- Its only exemption is `skip_always_ask`, built by `resolve_always_ask_skips`. That exempts Product only when the active flow's layout placement does not contain it. In SVX the XML layout places Product in the active flow, so the exemption is empty (`skip_always_ask_count 0`). The check is "is it on the flow", not "is it shown".

### 3.2 The layout does say it is hidden, and nothing reads that for forced anchors
- The SVX layout export (`configurationFlows_vx650_SysConfig`, Active) contains `productSelectionProduct_all` with **`hide: true`**, inside the tab titled "Hidden" (panel "Hidden Attributes").
- Every APX and Astro layout checked (`Astro25Configdata`, `Astro25_config_data`, `Config Layout APX Next`, `ConfigLayout_APX`, `APX _Next_config`) has the same attribute with `hide: false`.
- The engine's display order is built only from `hide: false` components, which is why `mountType_viSoln` (also `hide: true`) left the pending list after the layout was uploaded while Product did not: the forced-ask rule bypasses the display order.
- The XML layout nodes carry the same structure (`model_obj_type 1` tabs; country under "Product Configuration", Product under "Hidden").

### 3.3 The six quantities are internal fields behind an array table
- In the XML the `mountingType...Quantity_viSoln` attributes are `hidden=1`, `required=0`, and driven by the array attribute `mountingTypeArray_viSoln`. In the layout the grid is one `ARRAY_SET` ("Mounting Type / Quantity") under "Mandatory User Input", and the six quantity attributes sit in the "Hidden" tab.
- The engine has no representation of "a grid of per-row quantities behind an array controller"; the code already notes hidden quantity attributes can be surfaced as "unanswerable pending questions". They are asked as six scalar questions.
- The known gap is documented in `docs/cpq/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_GRID_PLAN.md` (written against an earlier workspace; status there "Proposed").

### 3.4 No "required" signal exists for SVX, so everything visible and unfilled is asked
- The XML marks every SVX attribute `required=0`.
- `attrSequence`, `whitelist` and `defaultInAttr` have **no rows for the SVX CPQ model** (checked in both copies of `attrSequence`, 47,369 and 46,913 rows). There is no `Seq` and no `R/O` flag for SVX.
- The layout JSON has no `required` flags either (all `False`).
- With no required signal, the flow's "pending" means "visible and unfilled", not "required".

### 3.5 The SVX workspace cannot resolve its own model, so it falls back to APXNEXT
- SVX has **no base model**: `BaseModelToConfig` has `baseModel = N/A`, family `videoSolutions_BOM`, line `mobile_BOM`, CPQ model `VX650_BOM`, variable name `vX650_BOM`. `CPQModelHierarchy` has `VX650` and `VX650_BOM`. Ask's product name `videoSolutions_BOM` is the family.
- In the workspace, `ws1188_cpqmodelhierarchy` holds 2 rows (the full file has 3,138) and `BaseModelToConfig` was skipped (`CBI_BML_NOT_FOUND`: no ingested script reads it). Model resolution has nothing to match, so it returns `NO_TIER_RESULT` and uses the fixed APXNEXT pair.

### 3.6 The turn cap is a message, not a stop
- `MAX_TURNS = 5` only switches the reply to the "incomplete" wording; questioning continues. The cap counts turns spent on optional fields, and the message tells the customer the configuration is incomplete although the real screen's mandatory fields were already satisfied.

## 4. Attribute order for SVX (where it can come from)

- `attrSequence`, `whitelist`, `defaultInAttr`: nothing for SVX.
- The layout is complete and ordered. The main tab ("Product Configuration", 45 attributes): the descriptive blocks, then "Mandatory User Input" (country, UDCC help, Solution Type, help text, Subscription Duration, Select Model, refresh and camera fields, mounting grid), "Recommended Configuration" (13 attributes), "Add On Accessories" (4), "Order Information" (10). The other tabs: "Hidden" (75), "Accessories" (16), "Bill of Materials" (1).
- This matches the real screen text supplied for the same request.

## 5. Fix needed

### 5.1 Honour the layout's explicit `hide` for forced-ask anchors (generic, data-driven)
- For the Product and select-model always-ask rules, add the attributes the layout explicitly marks `hide: true` to the exemption set. Only an explicit `true` counts; an attribute missing from the layout is not treated as hidden; no layout changes nothing.
- It must stay not asked **and** not blind-filled. The fill tiers already refuse the first-option fill for a skipped Product, with a comment citing the live "APX6500" incident.
- APX NEXT and Astro are unaffected because their layouts show Product (`hide: false`).
- Follow-up: replace the literal `productSelectionProduct_all` rule with the same layout-first test (visible in the layout, and `R` in `attrSequence` where that table covers the catalog), so no catalog-specific name remains.

### 5.2 Treat the mounting quantities as one optional grid
- Do not ask the hidden per-row quantity attributes one by one. Ask the grid once, as the real screen does (whole number, 0 or blank), or leave it unanswered unless the customer wants mounts.

### 5.3 Define "required" for catalogs without `attrSequence` rows
- Use the derived required set (rules and layout) inside the main tab, and do not ask attributes outside it. This needs the layout flags to be on for the workspace.

### 5.4 Load the model tables the SVX workspace needs
- Upload the full `CPQModelHierarchy` and `BaseModelToConfig` so `VX650_BOM` (base model `N/A`) resolves and the static APXNEXT fallback is no longer used.
- `BaseModelToConfig` is skipped by the CSV BML loader because no ingested script reads it. Either ingest the util-library XML into the workspace first (hypothesis, not verified) or load that table without requiring a referencing script.

### 5.5 Make the turn cap stop meaning "incomplete"
- End questioning once the screen's mandatory fields are met and move to Recommended Configuration. The cap should not count turns spent on optional or hidden fields.

## 6. Risks

- A catalog whose layout wrongly marks a needed anchor `hide: true` would stop asking it; the layout is the only visibility source the engine has, and a hidden attribute is not asked by the real screen either.
- Loading `BaseModelToConfig` without a referencing script bypasses the CSV BML gate; test on one workspace first.
- The quantity grid change touches the array-set payload path; it needs its own tests.

## 7. How to verify

- Fresh SVX chat on 1214: `ask.answer.branch` turn 1 `open_fields` should no longer contain `productSelectionProduct_all`; `skip_always_ask_count` should be above 0.
- The six quantity attributes should not appear as separate questions.
- `ARYX_ASK_MODEL_FALLBACK_STATIC` should not fire for SVX after the model tables are loaded.
- APX NEXT and Astro chats: Product still asked (their layouts show it).
- The reply should reach Recommended Configuration without the "incomplete" wording.
