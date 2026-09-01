# CPQ Beautify — Mandatory User Input Section Miscategorization

**Date:** 2026-08-19
**Status:** Implemented — Tier C shipped for beautify and the summary (config_data
deliberately excludes it; see `docs/CPQ_ConfigData_Payload_Mandatory_Fix_Scope_2026_08_19.md`).
**Scope note (2026-08-19, later same day):** the same root cause was also confirmed in
`build_payload`'s `config_data` JSON-preview payload (a THIRD consumer of `_is_mandatory_
input_attr`, alongside beautify and the summary) — see "config_data (JSON Preview Payload)"
below.

## Implementation (2026-08-19)

Shipped as one coordinated patch:

- `data_table_resolver.governed_required_attr_names_for_base_model` — the Required-only
  sibling of `governed_attr_names_for_base_model`, filtered to `optionOrReqFlag == "R"`.
- `CpqEngine._RECOMMENDED_CONFIG_ONLY_VNS` — the 10 curated Recommended-Configuration-only
  variable names.
- `CpqEngine.mandatory_tier_c_vns(filled, workspace_id, catalog_prefix, cache)` — resolves
  `cpq_model` candidates the same way `_suppress_ungoverned_attrs` does, unions each
  candidate's Required attr names, then excludes `_RECOMMENDED_CONFIG_ONLY_VNS` members and
  anything `resolve_whitelist_values` confirms has real constraint-shaped (Whitelist/
  Defaultinattr) coverage. Returns `frozenset()` (never `None`) when inputs are unavailable.
- `_is_mandatory_input_attr` gained a `required_vns` parameter (default `None`, preserving
  every pre-existing caller's Tier A/B-only behavior byte-for-byte) implementing Tier C.
- `_is_summary_excluded` gained an `is_mandatory` parameter (default `False`) — skips the
  boolean-value/`select_type=="boolean"` exclusion when the caller has independently
  confirmed the attribute is Mandatory, fixing the `isProvisioningRequiredInCloudEnv_astro`
  drop.
- `_filled_summary_triples`'s `rule_governed_ids is not None` branch now filters directly by
  `_is_mandatory_input_attr(...)` instead of its own separate "rule-governed entity +
  active-source + curated Associated-Options fragment" narrowing — the summary's item list is
  now exactly the Mandatory set. `required_vns` and `is_mandatory` are threaded through
  `filled_summary_pairs`, `render_filled_summary`, `categorized_summary_groups`,
  `_beautify_sectioned_rows`, `beautify_rows`, and `beautify_text`.
- `ask_api._cpq_summary_text` gained a `filled` parameter (the raw, non-display filled dict)
  used only to compute `required_vns` via `mandatory_tier_c_vns`; all 11 call sites now pass
  `filled=session.filled`. The beautify call site computes `required_vns` once and passes it
  to both `beautify_text`/`beautify_rows`.

**Known, deliberate side effect**: `_beautify_sectioned_rows` now passes `sources=filled_source`
into `_filled_summary_triples` (previously omitted entirely), which means `_is_summary_excluded`'s
hidden-attr carve-out (`attr.hidden and source != "user"`) now applies to beautify too — a
user-answered hidden attr (e.g. a grid-quantity companion with no visible menu) now survives in
beautify exactly as it already did in the summary, instead of always being excluded regardless
of source. This aligns beautify with the summary's own existing, intentional carve-out rather
than introducing new behavior — not flagged as a regression.

**Test coverage added**: `test_cpq_summary_active_sources.py` rewritten (9 tests) to reflect
the new contract — a `source == "rule"` value no longer survives by default (matches
`config_data`'s own contract), only via Tier C; `test_cpq_beautify_summary_tier_c_2026_08_19.py`
(8 new tests) covers Tier C inclusion/exclusion, `mandatory_tier_c_vns`'s three exclusion
paths, the boolean-gate fix, and beautify's section-switching via Tier C.
`test_cpq_2026_07_28_fixes.py`'s `_llm_first_gate_setup` fixture updated to mock
`llm_runtime.chat` — the redesigned summary now reaches its real LLM-narration call for a
scenario (a user-answered, non-rule-governed attribute with no rules loaded) that previously
produced an empty summary and never reached that call at all.

Full CPQ+BML suite: same 16 pre-existing failures throughout, 1249 passing (up from 1241).

## Problem Statement

Comparing a live `beautify_text` output against the native APX NEXT UI screenshot's actual
"Mandatory User Input" box (Country, Hardware Version, Product, Configuration Type, Software
Bundles, Software Release, Is-provisioning-required, Solution Type, Duration, Application
Services Bundle Duration + checklist, Wireless Carrier, Battery Type, Include a Spare — 13
fields), the beautify output only classifies **4** attributes as "Mandatory User Input"
(Product ×2, Base Model, Hardware Version). Every other field the screenshot shows inside that
box — Ultimate Destination Country, Configuration Type, Software Bundles, Software Release,
Solution Type, Duration, Application Services Bundle Duration, Wireless Carrier, Battery
Type — lands in "System-Configured / Recommended" instead. This is a real miscategorization,
not a display preference.

### Beautify output observed (excerpt)

```
**Mandatory User Input:**
Product                                                     : aSTRO25_bom
Base Model                                                  : H55TGT9PW8BN
Product                                                     : APX NEXT Enhanced
Hardware Version                                            : APX NEXT (4G LTE+5G)

**System-Configured / Recommended:**
Ultimate Destination Country                                : United States
Configuration Type                                          : Software Bundles
Software Bundles                                            : Core Trunking Bundle, ...
Solution Type                                               : Radio Management (MSI U.S. Hosted)
...
Package Type                                                : Single Pack Clamshell
...
```

## Root Cause

`_is_mandatory_input_attr` (`src/aryx/cpq/engine.py:11305`) classifies an attribute as
"Mandatory User Input" only when:

- **Tier A** — a structural anchor: Hardware Version, `productSelectionProduct_all`, or a
  `basemodel`/`selectmodel`-named attribute; OR
- **Tier B** — matches `_DECISION_REQUIRED_KEYS = {"country", "region"}` **and**
  `filled_source == "user"`; OR
- **Bare fallback** — `filled_source == "user"` (the customer directly typed/clicked it
  *this turn*).

```python
def _is_mandatory_input_attr(
    self, vn: str, attr: "ConfigAttr | None", source: str | None,
) -> bool:
    vn_flat = vn.lower().replace("_", "")
    tier_a = attr is not None and (
        vn == "productSelectionProduct_all"
        or self._is_hardware_version_attr(attr)
        or "basemodel" in vn_flat
        or "selectmodel" in vn_flat
    )
    tier_b = (
        any(dk in vn_flat for dk in _DECISION_REQUIRED_KEYS)
        and source == "user"
    )
    return tier_a or tier_b or source == "user"
```

This conflates two different concepts:

1. "The customer directly answered this **this turn**" (`filled_source == "user"`), and
2. "This field **lives in** the native UI's Mandatory User Input box."

The screenshot shows the Mandatory User Input box also contains fields that are
**pre-populated with a catalog default the customer never had to touch** — Software Release
defaults to "Baseline Release," Solution Type/Duration are pre-selected dropdowns, Battery
Type has a default. These are still editable Mandatory-box fields in the real UI; they are
just not `source == "user"` this turn (their `filled_source` is `"rule"`, `"default"`, or
similar). The heuristic silently drops all of them into "Recommended," which is factually
wrong for these specific fields.

## Compounding Issue (confirmed separately, still present here)

`isProvisioningRequiredInCloudEnv_astro` — a genuine Mandatory field per the screenshot, with
real downstream consequences (the ATO/MSAC provisioning-delay warning text shown beneath it)
— does not appear in **either** section. `_is_summary_excluded` unconditionally drops any
boolean-shaped value (`{"yes", "no", "true", "false"}`) before the Mandatory/Recommended split
ever runs:

```python
def _is_summary_excluded(self, variable_name, display_label, value, attr, source=None) -> bool:
    if value.strip().lower() in self._BOOLEAN_DISPLAY_VALUES:
        return True
    ...
```

This check has no gate on caller type — unlike the later narrowing block in
`_filled_summary_triples`, which is correctly scoped to `rule_governed_ids is not None`
(summary-only). The boolean exclusion applies to **every** caller, including beautify's
full-detail dump.

## Not a Bug

"Wireless Carrier" (`wirelessCarrier_astro`) itself is absent from the beautify list — only
"Carrier Selection" (`carrierSelectionMultiSelect_astro`) appears. This is consistent with an
earlier screenshot showing Wireless Carrier as currently **unfilled/invalid** ("Current
selection is invalid, please change to a valid option") — it correctly would not appear in a
filled-values dump. No action needed here.

## AttrSequence R/O Availability — Confirmed Feasible

Investigated whether AttrSequence's `optionOrReqFlag` (the real R/O signal) is already
loaded/queryable at the point `beautify_rows`/`beautify_text` get called. Confirmed yes, with
no new DB round-trip needed:

- `data_table_resolver._load_all_tables(workspace_id, catalog_prefix, cache)` already fetches
  the raw ingested `sequence_rows` (AttrSequence) live from Postgres, **including the
  `optionOrReqFlag` column** (per the shape docstring, `data_table_resolver.py:27`) — with a
  short-TTL cache keyed by `(workspace_id, catalog_prefix)`.
- `governed_attr_names_for_base_model(cpq_model, base_model, workspace_id, catalog_prefix, cache)`
  already reads from those same `sequence_rows`, filtered to `(cpq_model, base_model)` — but
  only extracts `AttrName`, discarding `optionOrReqFlag`.
- This resolver chain is already invoked earlier in the same request
  (`_suppress_ungoverned_attrs` → `_cpq_model_candidates`, part of `evaluate_rules_loop` /
  STEP 3) — well before `beautify_rows`/`beautify_text` are called at
  `ask_api.py:11515-11518`. `req.workspace_id`, `catalog_prefix` (`attrs[0].catalog_prefix`),
  and `session.filled` (with `modelSelectionbaseModel_astro`/`productSelectionProduct_all`)
  are all already resolved and in scope at that call site.

**Conclusion:** a small new sibling resolver (e.g.
`governed_required_attr_names_for_base_model`, mirroring the existing function but keeping
only rows where `optionOrReqFlag == "R"`) is all that's needed. No new plumbing, no new DB
round-trip — same cached `_load_all_tables` call, one more column read off rows already
fetched.

## Revised Design — One Mandatory Set, Two Consumers

Per explicit requirement: **the summary must show exactly the Mandatory User Input
attributes — all of them, no more, no less.** This simplifies the original 3-fix plan into
one unified mechanism instead of two separately-maintained lists (a beautify reclassification
list and a separate summary-exclusion list):

1. **Extend `_is_mandatory_input_attr` with Tier C**: an attribute is Mandatory when
   `governed_required_attr_names_for_base_model(...)` says `optionOrReqFlag == "R"` for the
   active `(cpq_model, base_model)` **and** it is not in the curated
   `_RECOMMENDED_CONFIG_ONLY_VNS` exclusion set (the 10 confirmed Recommended-only
   attributes: Feature Type, Service Type, DMS Duration, Antenna Type, Carry Type, System
   Key, Device Management Training, Train the Trainer Training, Package Type, Test
   Results/Rated Audio Printout Label). Tier A/B and the `source == "user"` fallback stay
   unchanged — Tier C only ADDS coverage for defaulted-but-editable Mandatory fields
   (Configuration Type, Software Bundles, Software Release, Solution Type, Duration,
   Application Services Bundle Duration, Wireless Carrier, Battery Type, Include a Spare,
   Country).
2. **Fix the boolean-drop bug, scoped to mandatory attributes only**: `_is_summary_excluded`'s
   unconditional boolean-value check must not fire when `_is_mandatory_input_attr(...)` is
   True for that attribute — this is what currently hides `isProvisioningRequiredInCloudEnv_astro`
   even though it is genuinely Mandatory. Non-mandatory boolean-valued attrs keep today's
   exclusion behavior unchanged.
3. **Summary = exactly the Mandatory set**: instead of the current `rule_governed_ids`-based
   "talking points" narrowing (which targets a different goal — Associated-Options business
   relevance — and both over- and under-includes relative to the real Mandatory box), the
   summary's item list becomes: every filled attribute where `_is_mandatory_input_attr(vn,
   attr, source)` is True, after only the non-boolean-related base exclusions (HTML/layout
   noise, secondary/warranty naming, product-label redundancy) — no separate curated
   exclusion list needed for summary; Tier C's own exclusion set already keeps Package Type
   and its 9 siblings out, and fix #2 already keeps the genuinely-Mandatory booleans in.

This means **beautify's "Mandatory User Input" section and the summary now derive from the
identical `_is_mandatory_input_attr` signal** — they can never silently drift apart on what
counts as Mandatory, which was the original design intent stated in `_is_mandatory_input_attr`'s
own docstring but never actually achieved because the summary path used a separate,
independently-maintained narrowing mechanism instead of this signal.

## Ground Truth vs. Mechanically-Computed Set — Confirmed Gap

Before implementing Tier C, the two candidate Mandatory-attribute lists were compared directly:

**Ground truth (13 attributes)** — confirmed by reading the native UI screenshot's actual
"Mandatory User Input" box:

| # | Label | Variable |
|---|---|---|
| 1 | Ultimate Destination Country | `ultimateDestinationCountry_astro` |
| 2 | Hardware Version | `hWVersion_astro` |
| 3 | Product | `productSelectionProduct_all` |
| 4 | Configuration Type | (Software Bundles / Custom Configuration radio) |
| 5 | Software Bundles | `softwareBundlesBundleType_astro` (or per-bundle checkboxes) |
| 6 | Software Release | `baselineReleaseSW_astro` |
| 7 | Is provisioning required in cloud? | `isProvisioningRequiredInCloudEnv_astro` |
| 8 | Solution Type | `solutionTypeDevices_astro` |
| 9 | Duration | `solutionTypeDuration_astro` |
| 10 | Application Services Bundle Duration | `applicationServicesIntroBundle_astro` / `applicationServicePromotionalDuration_astro` |
| 11 | Application Services (checklist) | `applicationServicesSelection_astro` |
| 12 | Wireless Carrier | `wirelessCarrier_astro` |
| 13 | Battery Type | `batteryType_astro` |
| — | Include a Spare | (toggle, exact variable not yet confirmed) |

**Mechanically-computed via raw `optionOrReqFlag == 'R'` minus the 10-item curated exclusion
(37 candidates)** — live-queried against workspace 93: 694 R-flagged AttrSequence rows / 44
distinct attribute names for APXNEXT* CPQModels; minus the 10 curated Recommended-only names
(7 of which actually overlap the 44) leaves **37**, including attributes ground truth does
NOT list as Mandatory: `modelSelectionKeypadType_astro`, `multikeyType_astro`,
`modelSelectionFrequencyBands_astro`, `sIMCardSelection_astro`, `modelSelectionHousing_astro`,
`operationModeType_astro`, and others.

**Why the gap exists:** Shylaja Shetty's own breakdown puts most of these 24 extra attributes
in her *first* category — "Auto-Resolved by Data Tables" (Region, Keypad, Multikey, Antenna,
Battery, Carry, Packing, Documentation, Services, Billing, Delay, etc.) — distinct from her
*third* category, the genuinely field-combination/user-driven set (Customer UIN, Country, HW
Version, Frequency Band, Cloud Provisioning, Application Services, SIM/Carrier Selection).
`optionOrReqFlag == 'R'` only asserts "must end up with SOME value" — it does not distinguish
*how* that value gets there. Raw R over-includes relative to the true Mandatory-box set by
including attributes a Whitelist/Defaultinattr row auto-resolves without ever showing the
customer an editable field.

## Revised Design — One Mandatory Set, Three Consumers

Per explicit requirement: **the summary must show exactly the Mandatory User Input
attributes — all of them, no more, no less.** Combining the AttrSequence-availability finding
above with the ground-truth-vs-computed gap, Tier C needs a second condition beyond the R
flag, and the summary switches to using this same signal directly rather than its own
separately-maintained narrowing:

1. **Tier C, refined**: an attribute is Mandatory when AttrSequence's `optionOrReqFlag == "R"`
   for the active `(cpq_model, base_model)` **and** it is not in the curated
   `_RECOMMENDED_CONFIG_ONLY_VNS` exclusion set (the 10 confirmed Recommended-only attributes)
   **and** no ingested constraint-shaped Data Table row (Whitelist or Defaultinattr — both
   pooled into the same shape bucket by `data_table_resolver._load_all_tables`) resolves it
   for this `(cpq_model, base_model)`. The third condition is the fix for the "37 vs. 13"
   over-inclusion gap: `resolve_whitelist_values(cpq_model, base_model, attr_var_name, filled,
   workspace_id, catalog_prefix)` already returns `None` exactly when "no ingested constraint
   table has any row at all for this (cpq_model, base_model, attr_var_name)" — reusable as-is
   for this existence check, no new resolver needed for this half. A new sibling resolver
   (`governed_required_attr_names_for_base_model`, mirroring the existing `governed_attr_names_
   for_base_model` but filtered to `optionOrReqFlag == "R"`) is still needed for the R-flag
   half. Tier A/B and the `source == "user"` fallback stay unchanged — Tier C only ADDS
   coverage for defaulted-but-editable Mandatory fields (Configuration Type, Software Bundles,
   Software Release, Solution Type, Duration, Application Services Bundle Duration, Wireless
   Carrier, Battery Type, Include a Spare, Country) that are genuinely unresolved by any data
   table.
2. **Fix the boolean-drop bug, scoped to mandatory attributes only**: `_is_summary_excluded`'s
   unconditional boolean-value check must not fire when `_is_mandatory_input_attr(...)` is
   True for that attribute — this is what currently hides `isProvisioningRequiredInCloudEnv_astro`
   even though it is genuinely Mandatory. Non-mandatory boolean-valued attrs keep today's
   exclusion behavior unchanged.
3. **Summary = exactly the Mandatory set**: instead of the current `rule_governed_ids`-based
   "talking points" narrowing (which targets a different goal — Associated-Options business
   relevance — and both over- and under-includes relative to the real Mandatory box), the
   summary's item list becomes: every filled attribute where `_is_mandatory_input_attr(vn,
   attr, source, required_vns)` is True, after only the non-boolean-related base exclusions
   (HTML/layout noise, secondary/warranty naming, product-label redundancy).

This means **beautify's "Mandatory User Input" section and the summary now derive from the
identical, three-tier `_is_mandatory_input_attr` signal** — they can never silently drift apart
on what counts as Mandatory, which was the original design intent stated in
`_is_mandatory_input_attr`'s own docstring but never actually achieved because the summary path
used a separate, independently-maintained narrowing mechanism instead of this signal.

### Threading required for implementation

`_is_mandatory_input_attr` needs a new optional `required_vns: frozenset[str] | None = None`
parameter (default `None` preserves every existing caller's Tier A/B-only behavior byte-for-
byte). A new public method, `mandatory_tier_c_vns(filled, workspace_id, catalog_prefix, cache)`,
computes that frozenset once per call using the resolvers above, resolving `cpq_model`
candidates the same way `_suppress_ungoverned_attrs` already does (`_cpq_model_candidates`).
Both `beautify_rows`/`beautify_text` (via `_beautify_sectioned_rows`) and the summary chain
(`_cpq_summary_text` → `categorized_summary_groups`/`render_filled_summary` →
`filled_summary_pairs` → `_filled_summary_triples`) need this frozenset threaded through as one
new optional parameter each — every signature defaults it to `None`, so no existing caller's
behavior changes unless explicitly opted in.

## config_data (JSON Preview Payload) — Same Root Cause, Confirmed for 4 More Attributes

A live `config_data` sample (from `build_payload(..., scope_required_and_edited=True)`, the
web UI's JSON/share-button preview payload) was reviewed:

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

Only 2 attributes are present. Four confirmed, pure-user-input Mandatory fields with **no
catalog default at all** are missing entirely:

- `ultimateDestinationCountry_astro` (Ultimate Destination Country)
- `wirelessCarrier_astro` (Carrier Selection / Wireless Carrier)
- `modelSelectionFrequencyBandMsl_astro` (Frequency Band Msl)
- `isProvisioningRequiredInCloudEnv_astro` (Is provisioning required in cloud?)

### Root cause — the identical mechanism, seen from a third angle

`build_payload(scope_required_and_edited=True)` scopes `config_data` using the SAME
`_is_mandatory_input_attr` function documented above (Tier A/B only, today). None of these
four attributes are Tier A (only Hardware Version/Product/basemodel/selectmodel qualify).
Tier B only recognizes `_DECISION_REQUIRED_KEYS = {"country", "region"}` as a variable-name
fragment — `wirelessCarrier_astro`, `modelSelectionFrequencyBandMsl_astro`, and
`isProvisioningRequiredInCloudEnv_astro` don't match ANY fragment in that set, so Tier B can
never include them regardless of source. `ultimateDestinationCountry_astro` DOES match the
"country" fragment, but Tier B additionally requires `source == "user"` literally — so even
Country only qualifies if its `filled_source` is the exact string `"user"`.

That leaves all four dependent entirely on the bare fallback: `source == "user"`. This is
where the real gap is — confirmed live in `engine.py`/`ask_api.py`:

- **`ultimateDestinationCountry_astro`** is very likely tagged `source="hint"`, not `"user"`,
  when extracted directly from a compound opening sentence (e.g. "I want to configure APX
  NEXT for **USA**") — confirmed live: `engine.py`'s `auto_fill` sets `source = "hint"` when a
  value comes from the hints dict rather than a dedicated pending-question turn
  (`engine.py:8145`). It could also be tagged `"country_derived"` in other flows. Neither
  string is `"user"`.
- **`wirelessCarrier_astro`** and **`modelSelectionFrequencyBandMsl_astro`** are frequently
  populated as a side effect of a Hardware Version/Product change — `ask_api.py` tags these
  cascade-derived re-fills `"cascade"` (the attribute that changed directly) or
  `"cascade-dependent"` (everything narrowed as a consequence) at `ask_api.py:2552` and
  `ask_api.py:3829`. `modelSelectionFrequencyBandMsl_astro` specifically is called out
  elsewhere in `engine.py` (line ~7319) as a value that regularly lands via exactly this kind
  of derived path, not a dedicated question.
- **`isProvisioningRequiredInCloudEnv_astro`** would get `source="user"` normally if answered
  via a direct yes/no pending-question turn (`ask_api.py:10897/10901/10960` all set
  `filled_source[pending_var] = "user"` for a genuine answered turn) — but if it was instead
  captured via a compound-sentence multi-attribute hint extraction (Amendment 17,
  `_llm_extract_multi_attr_hints`) alongside other facts in one message, it would get
  `source="hint"` instead, despite being just as genuine a customer decision.

### The deeper insight — this codebase already has the right answer, just not applied here

The engine's OWN summary-narrowing logic already recognizes that a genuine per-turn decision
is not always tagged literally `"user"` — `_SUMMARY_ACTIVE_SOURCES` (`engine.py:12123`)
explicitly includes `{"rule", "country_derived", "user", "hint", "cascade",
"cascade-dependent", "product_anchor"}` as the full set of sources that represent "a rule
whose condition actually held, or the user's own answer/hint/cascade-driven change" — as
opposed to a "bland default/optional/auto fill nobody actually reasoned about." `_is_mandatory_
input_attr`'s bare fallback never adopted this broader, already-established set — it still
checks the single literal string `"user"`, which is why Country/Carrier/Frequency/Provisioning
disappear from `config_data` even when they are unambiguously genuine, deliberate customer
decisions.

### Implication for the Tier C design above

This is the SAME underlying defect already being fixed via Tier C for beautify/summary
(Section "Revised Design"), attacked from a different angle:

- Tier C (AttrSequence `R`-flag, minus curated Recommended-only, minus data-table-resolvable)
  would independently ALSO catch `ultimateDestinationCountry_astro` and
  `wirelessCarrier_astro` if they are genuinely R-flagged and have no Whitelist/Defaultinattr
  coverage — worth confirming once Tier C is implemented.
- `modelSelectionFrequencyBandMsl_astro` and `isProvisioningRequiredInCloudEnv_astro` need a
  SEPARATE fix regardless of Tier C: the bare fallback's source check should widen from the
  single literal `source == "user"` to the full `_SUMMARY_ACTIVE_SOURCES`-equivalent set (or a
  dedicated subset of it excluding purely-passive tags like plain `"rule"`/`"default"`) —
  otherwise a cascade-derived or hint-extracted genuine decision keeps disappearing from
  `config_data` no matter how Tier C is scoped, since neither of those two attributes is
  R-flagged as a primary decision the same way Country/Carrier likely are.
- This widened bare-fallback fix should apply to **all three consumers** (`build_payload`'s
  `config_data`, beautify, and the summary) at once, being the same shared `_is_mandatory_
  input_attr` function — consistent with the "one scoping key, three consumers" design intent
  already stated in that function's own docstring.

## Full Attribute-Level Exposure Analysis — Which Other Attributes Share This "hint"/"cascade"/"cascade-dependent" Risk

Investigated how broadly the `source != "user"` gap (Section "config_data") actually reaches,
beyond the 4 attributes already named. Two structurally distinct mechanisms, each traced to
its exact code location, then live-verified against workspace 93's real rule graph.

### "hint" — generic, catalog-wide, not attribute-specific

`engine.py`'s `auto_fill` hint-matching pass (~line 8077 onward) is a single, fully generic
loop: for **every** attribute `vn` being resolved, it checks every key in the turn's `hints`
dict for a **fragment match** against `vn` (`hk_flat in vn_flat or vn_flat in hk_flat`) —
there is no attribute allowlist here at all. Any attribute whose variable name shares a
fragment with anything the NLU/Tier-1 hint extractor pulled out of the customer's free-text
message gets `source = "hint"` once a value resolves this way (confirmed at line 8144-8145).
Country is a concrete, already-confirmed example (a dedicated "Priority 4: country alias
group" branch at line 8120 matches hint values against Country's own menu options
specifically) — but the mechanism itself is generic: **any** attribute is exposed the moment a
customer's opening or follow-up sentence happens to mention something that fragment-matches
its name. This cannot be reduced to a fixed enumerable list — it is a property of the
resolution mechanism itself, not of any particular attribute.

### "cascade" / "cascade-dependent" — driven by the real rule graph, IS enumerable per catalog

`find_cascade_dependents` (`engine.py:10432`) returns, for a changed attribute, every
attribute targeted by a hiding/recommendation/constraint rule whose `condition_attr_id`
matches the changed attribute (plus free-text decision-key siblings). `ask_api.py` tags the
changed attribute itself `"cascade"` and every one of these dependents `"cascade-dependent"`
(`ask_api.py:2552`, `:3829`). Unlike "hint," this IS enumerable for a given catalog — it is
exactly the rule graph rooted at whichever attribute changed.

**Live-verified against workspace 93** (joining `ApxnextCnofigdataBmConfigRuleInput` →
`ApxnextCnofigdataBmConfigRuleAction` on `rule_id`, filtered to rules whose condition
attribute is Hardware Version (`hWVersion_astro`), Product (`productSelectionProduct_all`),
or Country (`ultimateDestinationCountry_astro`)): **214 rules** are conditioned on one of
these three anchors, targeting **104 distinct attributes**. Every one of these 104 is
structurally exposed to `"cascade"`/`"cascade-dependent"` tagging the moment Hardware
Version, Product, or Country is set or changed — including the very first time, since this
engine processes the initial selection through the same cascade machinery as a later change.

Grouped by relevance to this analysis:

| Group | Examples (of the 104) |
|---|---|
| Already-confirmed missing from `config_data` | `wirelessCarrier_astro`, `carrierSelectionMultiSelect_astro`, `modelSelectionFrequencyBandMsl_astro`, `isProvisioningRequiredInCloudEnv_astro` |
| Overlap with Tier C's 37-candidate set (Section "Ground Truth vs. Mechanically-Computed Set") | `antennasType_astro`, `batteryType_astro`, `beltClipType_astro`, `deviceManagementTraining_astro`, `dmsDuration_astro`, `documentationTestResultsRatedAudioPrintoutLabel_astro`, `modelSelectionbaseModel_astro`, `modelSelectionFrequencyBands_astro`, `modelSelectionHousing_astro`, `modelSelectionKeypadType_astro`, `modelSelectionRegion_astro`, `modelSelectionSubmersibleDeltaT_astro`, `multikeyType_astro`, `operationModeType_astro`, `packingPackageType_astro`, `preSalesEnggAcknowledgement_astro`, `sIMCardSelection_astro`, `selectSecondarySIMCard_astro`, `serviceActivationDelay_astro`, `serviceTypeAdditionalDMSCoverage_astro`, `softwareBundlesBundleType_astro`, `solutionTypeDevices_astro`, `subscriptionBillingAddDMSCoverage_astro` |
| Overlap with the curated `_RECOMMENDED_CONFIG_ONLY_VNS` (confirmed Recommended-Configuration-only, must NOT become Mandatory regardless of source) | `packingPackageType_astro`, `antennasType_astro`, `beltClipType_astro`, `deviceManagementTraining_astro`, `dmsDuration_astro`, `documentationTestResultsRatedAudioPrintoutLabel_astro`, `serviceTypeAdditionalDMSCoverage_astro` |
| Neither in Tier C's candidate set nor the curated exclusion (genuinely new findings) | `additionalSystemEnhancementFeatureType_astro`, `systemEnhancementFeatureType_astro`, `packageTypeBundles_astro`, `serviceType_astro`, `serviceTypeRSM_astro`, `rSMType_astro`, `videoRSM_astro`, `secureEncryptionType_astro`, `provAgencyId_astro`/`provAgencyName_astro`/`provAgencyType_astro` (provisioning-agency fields), `enableDualActiveSim_astro`, `applicationServicesSelection_astro`, `applicationServicesIntroBundle_astro`, `applicationServicePromotionalDuration_astro`, `additionalApplicationServices_astro`, `aTAKEnabledPackage_astro`/`aTAKNonPromoApplicationServices_astro` |
| Internal/master-string/help-text noise (never a real customer-facing Mandatory field regardless of source) | `hiddenConstraintMasterString_astro`, `hiddenConstraintMasterStringForBaseModel_astro`, `hiddenMasterStringForAstroPortable_astro`, `hiddenMasterStringForNonFrequencyParametricData_astro`, `hiddenUISequenceForModelSelection_astro`, `hiddenUISequenceMasterString_astro`, `defaultAttrValuesMasterString_astro`, every `...HelpText_astro`/`...Helptext_astro` variant, `cBPQRCode_astro`, `fedQRCode_astro`, `dataTableList_astro`, `ccArrayControl_astro`, `provAgenArrayControl_astro` |

### Practical implication

The "widen the bare fallback beyond literal `source == 'user'`" fix (Next Step item 4) has a
**much larger blast radius** than the original 4-attribute finding suggested — up to 104
attributes for this catalog alone are structurally exposed to non-`"user"` tagging via the
Hardware Version/Product/Country rule graph, before even counting the untraceable-by-query
"hint" exposure. This reinforces that the fix must be scoped carefully:

- The widened source set must stay restricted to genuinely-active decision tags
  (`"hint"`, `"cascade"`, `"cascade-dependent"`, `"country_derived"`, `"product_anchor"` — the
  existing `_SUMMARY_ACTIVE_SOURCES` set) — NOT bare `"rule"`/`"default"`/`"auto"`, which would
  wrongly promote purely-passive, never-reasoned-about fills into "Mandatory."
- Even with that restriction, the "internal/master-string/help-text noise" group above must
  stay excluded by some OTHER mechanism (the existing `_is_noise_var`/HTML-value checks in
  `_filled_summary_triples` already exclude most of these from summary/beautify; `build_payload`
  has its own separate `hide_in_trans`/`set_type` exclusions) — widening the source check alone
  must not be assumed to be sufficient, these other filters need to stay in the path for
  `config_data` too.
- The curated `_RECOMMENDED_CONFIG_ONLY_VNS` exclusion (already required for Tier C) becomes
  even more important once the source check widens — several attributes in the "overlap with
  curated exclusion" group above would otherwise flip into "Mandatory" for `config_data` too
  just by virtue of getting `"cascade-dependent"` on the very same turn Hardware Version is
  first set, despite being confirmed Recommended-Configuration-only.

## Cross-Reference

- `docs/CPQ_TrueUserRequired_Attributes_2026_08_19.docx` — establishes that AttrSequence's
  `optionOrReqFlag` is the real R/O signal, and that ~44 attributes are R-flagged for
  APXNEXT* CPQModels, of which only ~10 are genuinely "Recommended Configuration only."
- `docs/CPQ_PackageType_HardExclude_RCA_2026-08-19.docx` — the conversational-ask-flow
  counterpart of this same Mandatory-vs-Recommended distinction
  (`_NEVER_ASK_RECOMMENDED_ONLY_VNS` in `ask_api.py`).

## Next Step

Implement as one coordinated patch, now four fixes sharing the one `_is_mandatory_input_attr`
signal across all three consumers (beautify, summary, `config_data`):

1. The new `governed_required_attr_names_for_base_model` resolver + `mandatory_tier_c_vns`
   helper (Tier C: R-flag AND not curated-Recommended AND not data-table-resolvable).
2. The mandatory-gated boolean-exclusion fix (`_is_summary_excluded`, so
   `isProvisioningRequiredInCloudEnv_astro` stops disappearing from beautify/summary).
3. The summary's switch to filtering by `_is_mandatory_input_attr` directly instead of its own
   separate narrowing.
4. **Widen the bare-fallback source check** in `_is_mandatory_input_attr` from the single
   literal `source == "user"` to the same "genuine per-turn decision" set `_SUMMARY_ACTIVE_
   SOURCES` already establishes (`{"rule", "country_derived", "user", "hint", "cascade",
   "cascade-dependent", "product_anchor"}`, or a deliberately-chosen subset of it) — this is
   what's needed to stop `ultimateDestinationCountry_astro`, `wirelessCarrier_astro`,
   `modelSelectionFrequencyBandMsl_astro`, and `isProvisioningRequiredInCloudEnv_astro` from
   disappearing out of `config_data` specifically, independent of whether Tier C also happens
   to catch some of them.

The required-vns frozenset (fix #1) and the widened source set (fix #4) both thread through
`_is_mandatory_input_attr`'s call sites in beautify, the summary chain, AND `build_payload`'s
`config_data` scoping — all three as new, backward-compatible optional parameters defaulting to
today's behavior. No code has been changed as part of this analysis — pending go-ahead to
implement.
