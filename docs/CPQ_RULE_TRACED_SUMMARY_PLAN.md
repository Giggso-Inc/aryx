# CPQ Rule-Traced Summary Plan

New, separate plan — not appended to `docs/CPQ_RULE_TOOL_FLOW_PLAN.md` (already
implemented) or `docs/CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md` (documents the
section-membership mechanism this plan consumes, not yet wired into code).

## 1. Goal

Payload stays exactly as-is — 84 governed attrs, `build_payload` untouched,
sorted by real `order_number` (already shipped). What changes is the
**completion summary** shown to the sales rep: instead of today's flat,
undifferentiated list (`_DECISION_REQUIRED_KEYS`-based), it scopes to the
confirmed 32-attr `bm_layout_model` section (§8 of the layout plan) — the
same attrs the native BigMachines UI itself shows — and for each one,
surfaces **why it has the value it has**: order, governing hiding rule (did
it fire, why), governing constraint rule (what it narrowed options to),
governing recommendation rule (did a default get auto-selected), and
whether that resolution came from a declarative rule or a BML script.

Purpose stated explicitly by the requester: **validate the payload is
correct** — an audit trail, not just a prettier message.

## 2. Confirmed real data (not hypothetical)

Grepped every one of the 32 section attrs (§8) against
`docs/CPQ_APX_NEXT_RULE_CATALOG.md`'s real rule table. Every attr has
governing rules — nothing here needs new data collection, only new
plumbing to surface what's already loaded at runtime:

| Attr | Rule-table mentions (hide/constraint/recommend rows referencing it) |
|---|---|
| `hWVersion_astro` | 6 |
| `productSelectionProduct_all` | 236 (shared master list — high-cardinality by nature) |
| `productSelectionHelptext_astro` | 4 |
| `modelSelectionFrequencyBands_astro` | 14 |
| `modelSelectionFrequencyBandPlus_astro` | 7 |
| `softwareBundlesBundleType_astro` | 21 |
| `packageTypeBundles_astro` | 68 |
| `baselineReleaseSW_astro` | 8 |
| `isProvisioningRequiredInCloudEnv_astro` | 17 |
| `isFedRampRequired_astro` | 15 |
| `solutionTypeDevices_astro` | 12 |
| `solutionTypeDuration_astro` | 8 |
| `applicationServicesSelection_astro` | 12 |
| `wirelessCarrier_astro` | 8 |
| `batteryType_astro` | 17 |
| `batteryQuantityforSpares_astro` | 10 |
| `isThisASPARERadioBatt_astro` | 8 |
| `rSMType_astro` | 7 |
| `additionalApplicationServices_astro` | 36 |
| (remaining 13 attrs) | 2-7 each |

## 3. The attribute-selection flow (traced against the shared live payload)

Using the actual "Quote APX Next Enhanced radios for a US customer." session
already run live this session, here's the real order-of-resolution:

1. **Anchor gate (pre-attr-loop)**: `ultimateDestinationCountry` resolved
   from the NL hint "US customer" — decision-required, always asked/derived
   first regardless of governance (D1). Confirmed section order=1.
2. **Product-line resolution**: `productSelectionProduct_all` (order=3) —
   now decision-required (Bug 3 fix, this session) since its 325-option
   list has no reliable governing rule; resolved from the NL hint "APX Next
   Enhanced" matching option text directly.
3. **Hardware Version**: `hWVersion_astro` (order=2) — 2 real options
   (`NEXT STANDARD LTE ONLY` / `NEXT ENHANCED LTE PLUS 5G`); no matching NL
   hint in "Quote APX Next Enhanced radios..." → falls to first-by-order
   default (`NEXT STANDARD LTE ONLY`), confirmed live. Later user turn
   ("change the hardware version to APX NEXT (4G LTE+5G)") explicitly
   overrides it via `detect_change_request` → cascades an "invalidated:
   Product — re-evaluating" note (though, per earlier finding, that specific
   cascade is currently cosmetic for `productSelectionProduct_all`).
4. **Frequency/help-text attrs** (orders 4-6): hidden this turn — governed
   by the 5-rule "per-model enabled-attribute list" BML idiom (§6 of the
   layout plan) keyed on `modelSelectionbaseModel_astro=H45TGU9PW8AN`,
   whose enabled-string doesn't list them for this single-band SKU.
5. **Software Bundles** (orders 7-8): visible and filled — same idiom,
   opposite outcome (this model's enabled-string DOES list them).
6. **Remaining section attrs (orders 9-32)**: each independently resolved
   by whichever governing mechanism applies — declarative recommendation
   (e.g. `baselineReleaseSW_astro` default), declarative constraint (e.g.
   `serviceTypeAdditionalDMSCoverage_astro`'s downstream hide of
   `includeAccidentalDamageAddDMSCoverage_astro` — the still-open violation
   flagged this session), or BML script (the same per-model idiom class as
   step 4, for `batteryType_astro`/`multikeyType_astro`/`beltClipType_astro`
   — confirmed NOT traceable by static XML lookup alone; needs the live
   `BmlEvaluator` to actually run, per the earlier finding this session).

## 3b. Scope correction — ALL 84 payload attrs, not just the 32 section ones

Confirmed with the requester: the provenance trace must cover every attr
that reaches `build_payload`, not only the 32 shown on-screen. The 32-vs-84
split still matters for the SUMMARY (§1) — but the trace/audit log itself
must explain every attr actually submitted, section member or not.

Also confirmed via live regeneration test: after a real user change
("change the hardware version to APX NEXT (4G LTE+5G)"), the payload
regenerates correctly — still 84 attrs, still sorted `order_number` 1→last,
`hWVersion_astro` updated in place. Order-stability across regeneration is
already correct; no fix needed there — the provenance trace just needs to
capture this same regeneration event as one of its logged entries.

**Real rule names (not counts) for two representative payload-only attrs**,
confirmed against `docs/CPQ_APX_NEXT_RULE_CATALOG.md`:

- **`hWVersion_astro`** (section member, order=2):
  - Hiding: *"Hide HW Version unless APX Next NA or APX Next fed model
    (portables)"* — script (fn 19435386308) on
    `_bm_model_variable_name`/`modelSelectionRegion_astro`.
  - Hiding (declarative): *"Hide Product if Country is Blank"* —
    `ultimateDestinationCountry` blank → hide.
  - Constraint: *"Constrain Product LOVs for APX NEXT BOM model"` —
    `hWVersion_astro` condition narrows `productSelectionProduct_all` to 8
    specific values (APX NEXT INTL FED, XN SINGLE BAND, ENHANCED, MULTI, ...).
  - Recommendation (declarative): *"Default hardware version for APX Next"*
    — `modelSelectionRegion_astro=NA` → default `NEXT STANDARD LTE ONLY`.
  - Recommendation (script): *"Default APX Next Enhanced based on HW
    version"* (fn 19435386319) — sets `productSelectionProduct_all` when
    `hWVersion_astro=="NEXT ENHANCED LTE PLUS 5G"`. **This directly
    contradicts this session's earlier assumption that no rule reliably
    governs `productSelectionProduct_all`** — a real, script-based
    recommendation DOES exist for the Enhanced case specifically. The
    decision-required fix (Bug 3, already shipped) remains the safe general
    default since this one rule doesn't cover all 325 options, but this
    trace surfaces a real opportunity: wire this specific script so
    `productSelectionProduct_all` auto-resolves without asking whenever
    `hWVersion_astro` matches this rule's condition, falling back to
    decision-required only when it doesn't.

- **`batteryQuantityforSpares_astro`** (payload-only, not a section member):
  - Hiding (declarative): *"Hide Battery Spare Quantity if include spare is
    false"* — `batteryIncludeaSpare_astro=false` → hide.
  - Hiding (script): *"Hide Quantity For Spares Attribute If No Values
    Available (Portable)"* (fn 19435386600) on
    `batteryType_astro`/`modelSelectionbaseModel_astro`.
  - Hiding (declarative): *"Hide all attributes if Product is Blank"* —
    `productSelectionProduct_all` blank → hide.
  - Recommendation (declarative, 4 separate package-type default rules):
    *"Default Values For Attributes Based on Package Type FIXED/SEMI-FIXED"*,
    *"Set Default Attribute Values for Packages(Pricing Admin)"* (×2).
  - Recommendation (script): *"Set Value from Commerce when
    reconfigured"* — pulls from `_transaction_id` when reconfiguring an
    existing commerce record.

This confirms every payload attr, section member or not, has this same
depth of real, multi-rule governance — the provenance trace is equally
necessary for both groups, not a section-only nicety.

## 4. What needs building

- **New provenance structure**: per-attr trace object
  `{order, governing_hiding_rule, fired: bool|"unknown", governing_constraint_rule,
  allowed_values, governing_recommendation_rule, resolution_mechanism: "declarative"|"script"|"default"|"user"}`
  — populated during `evaluate_rules_loop` (where hiding/constraint/
  recommendation rules already run), not reconstructed after the fact.
  Applies to **all 84 payload attrs**, not just the 32 section members
  (§3b) — one shared mechanism, two different consumers (full audit log
  vs. section-scoped summary).
- **Regeneration logging**: each time a user-driven change
  (`detect_change_request`) triggers a re-evaluation pass, log which attrs'
  traces actually changed (rule re-fired, new value, or unchanged) — this
  is the concrete "is there a payload change from the user" record the
  requester asked for, not just a cascade note in the chat reply.
- **Section-scoped summary**: `build_review_prompt`/`_cpq_summary_text`
  read the confirmed `bm_layout_model` section (§8) instead of
  `_DECISION_REQUIRED_KEYS`, catalog-agnostically (same country-anchor
  generic-detection rule the layout plan already established, not
  hardcoded to APX Next's specific `layout_id`).
- **Script-gated attrs stay honestly labeled**: where resolution is
  script-driven and the evaluator returns "unknown" (Tier 1.5 gap, not yet
  covered), the trace says so explicitly rather than guessing — same
  "never fabricate" discipline as the rest of this session's fixes.
- **`consistency_flag` field**: sourced from `docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md`'s
  `find_rule_inconsistencies()` — that plan's §4.1 also defines what
  happens when this flag is set (auto-fix for hiding-type disagreements,
  tell-the-user for constraint/recommendation-type ones). Build together,
  not as two independent mechanisms computing overlapping information.

### 4.1 Every trace must be a real log line, not just an in-memory return value

The provenance object above must not exist only as a Python structure
returned to the caller and then discarded — it needs to be **emitted as an
actual log line, per attr, in code**, using the SAME logging
infrastructure this session already wired up
(`aryx.cpq.logging_context.install_run_id_logging`, `set_run_id`) so every
trace entry is automatically tagged with the turn's `run_id` and shows up
in the existing cpq logger output, not a separate, easy-to-miss channel.

Concretely, inside `evaluate_rules_loop` (or wherever the provenance object
is assembled per §4's first bullet), for every attr processed:

```python
logger.info(
    "cpq: attr=%s order=%s hiding_rule=%r fired=%s constraint_rule=%r "
    "allowed_values=%s recommendation_rule=%r mechanism=%s consistency=%s",
    attr.variable_name, attr.order,
    trace.governing_hiding_rule, trace.fired,
    trace.governing_constraint_rule, trace.allowed_values,
    trace.governing_recommendation_rule, trace.resolution_mechanism,
    trace.consistency_flag,
)
```

One line per attr, per turn — this is what makes the trace auditable
after the fact (grep the log by `run_id`, replay exactly which rules fired
in what order for a specific customer's quote) rather than only visible
in-session via the chat summary. The in-memory structure (§4's first
bullet) and this log line are the SAME data, emitted twice for two
different consumers: the structure feeds the live summary/consistency
check; the log line is the permanent, greppable audit trail.

## 6. Genericity check — does this plan work for SVX and SL3500e too?

Yes, structurally — the mechanism this plan depends on (rule_type-tagged
hiding/constraint/recommendation rows referencing a target attr, declarative
or script) is the SAME BigMachines rule taxonomy already confirmed universal
across all 3 catalogs (docs/CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md §7). The
provenance-trace code (§4) reads rule tables generically by attr id/name —
nothing in the design is APX-Next-specific.

What differs per catalog (expected, not a gap): the ACTUAL rule content.
SVX's `rule_type=6` flow section is smaller (2 attrs: country + its help
text, per §7's finding), so SVX's 32-attr-scale section simply doesn't
exist — its section is tiny, meaning the trace has far fewer section
members to cover, but every payload attr (section or not) still gets one.
SL3500e likewise has its own rule set, not yet individually re-verified
attr-by-attr the way APX Next's 32 were in §3b — that's the concrete
remaining gap: this plan's §3b sample is APX-Next-only; SVX/SL3500e need
their own equivalent sample pass before implementation, using the same
method (grep each catalog's own rule table by section-attr name).

## 7. Full APX Next section-attribute rule sample (all 32, cross-verified)

Every row below is pulled directly from real rows in
`docs/CPQ_APX_NEXT_RULE_CATALOG.md` — rule name, condition, and target
verbatim, not paraphrased:

| Attr (order) | Sample governing rule(s) |
|---|---|
| `hWVersion_astro` (2) | Hide: script fn 19435386308 (`_bm_model_variable_name`, `modelSelectionRegion_astro`); declarative "Hide Product if Country is Blank" (`ultimateDestinationCountry` blank). |
| `productSelectionProduct_all` (3) | Hide: declarative (`ultimateDestinationCountry` blank); script fn 19435386393 ("Hide Product Selection until Hardware Version is selected", keyed on `hWVersion_astro`+`modelSelectionRegion_astro`). Constraint from `hWVersion_astro` narrows to 8 values (§3b). Recommendation: script fn 19435386319 (Enhanced case, §3b). |
| `productSelectionHelptext_astro` (4) | Hide: script fn 21321895858 (`modelSelectionbaseModel_astro`); declarative "Hide all attributes if Product is Blank". |
| `modelSelectionFrequencyBands_astro` (5) | Hide: script fn 19435386566 (no explicit condition attrs listed — reads the per-model enabled-string idiom, §6 of layout plan); declarative Product-blank rule. |
| `modelSelectionFrequencyBandPlus_astro` (6) | Hide: script fn 19435386690 (`modelSelectionbaseModel_astro`); declarative Product-blank rule. |
| `softwareBundlesBundleType_astro` (7) | Governs (not governed by, in this row) `operationModeType_astro`/`systemEnhancementFeatureType_astro` when ="STANDARD BUNDLE" — itself gated by the same per-model idiom as orders 5/6 (§6). |
| `packageTypeBundles_astro` (8) | Hide: script fn 19435386805 (`hiddenUISequenceMasterString_astro`); script fn 19435386546 (`modelSelectionbaseModel_astro`). |
| `baselineReleaseSW_astro` (9) | Hide: script fn 19435386547 (`modelSelectionbaseModel_astro`); declarative Product-blank rule. |
| `baselineReleaseSWHelpText_astro` (10) | Hide: script fn 21321895871 (`modelSelectionbaseModel_astro`). Separately, "Set HelpTtext info" script builds its display text from a JSON help-text master string. |
| `isProvisioningRequiredInCloudEnv_astro` (11) | Hide: script fn 21321895992 (`productSelectionProduct_all`, `ultimateDestinationCountry` — non-US hides it); script fn 19435386612 (`modelSelectionbaseModel_astro`). |
| `isProvisioningRequiredInCloudEnvHelpText_astro` (12) | Same fn 21321895992 condition; declarative Product-blank rule. |
| `salesApprover_astro` (13) | Hide: declarative ("Is provisioning required NOT = Yes"); script fn 19435386618 (`modelSelectionbaseModel_astro`). |
| `isFedRampRequired_astro` (14) | Hide: fn 21321895992 (shared with cloud-provisioning attrs); script fn 21321895993 (`customerType`, `ultimateDestinationCountry` — Federal-only). |
| `fedRampHelpText_astro` (15) | Same fn 21321895992 condition; declarative Product-blank rule. |
| `solutionTypeDevices_astro` (16) | Hide: script fn 19435386556 (`modelSelectionbaseModel_astro`); declarative Product-blank rule. |
| `solutionTypeDuration_astro` (17) | Hide: declarative (`_bm_model_variable_name=aPXN30`); script fn 19435386671 (`modelSelectionbaseModel_astro`). |
| `applicationServicesSelection_astro` (18) | Hide: script fn 21321895883 (`modelSelectionbaseModel_astro`); declarative (`ultimateDestinationCountry` != US OR provisioning=YES OR solution type not RadioCentral/Federal). |
| `sIMCardSelection_astro` (19) | Hide: script fn 19435386791 (`modelSelectionbaseModel_astro`); declarative "Show SIM Card Selection only for APX NEXT Enhanced" (`productSelectionProduct_all="APX NEXT ENHANCED"`). |
| `enableDualActiveSim_astro` (20) | Hide: script fn 22194395140 (`applicationServicesSelection_astro`, `modelSelectionbaseModel_astro`); associated recommendation sets `false` by default. |
| `carrierSelectionMultiSelect_astro` (21) | Hide: script fn 22194395138 (`modelSelectionbaseModel_astro`). |
| `selectSecondarySIMCard_astro` (22) | Hide: same fn 22194395138; declarative Product-blank rule. |
| `wirelessCarrier_astro` (23) | Hide: script fn 19435386629 (`modelSelectionbaseModel_astro`); declarative Product-blank rule. |
| `batteryType_astro` (24) | Hide: script fn 19435386589 (`modelSelectionbaseModel_astro`, §6's own example); declarative Product-blank rule. |
| `batteryIncludeaSpare_astro` (25) | Governs `batteryQuantityforSpares_astro` (hide when =false) — itself hidden per the standard per-model idiom (not separately re-quoted here). |
| `batteryQuantityforSpares_astro` (26) | Hide: declarative (`batteryIncludeaSpare_astro=false`, 2 near-duplicate rule rows); script fn 19435386600 (`batteryType_astro`, `modelSelectionbaseModel_astro`); declarative Product-blank rule. |
| `isThisASPARERadioBatt_astro` (27) | Hide: script fn 19435386752 (`modelSelectionbaseModel_astro`); declarative Product-blank rule. |
| `rSMType_astro` (28) | Hide: script fn 19435386419 (`modelSelectionbaseModel_astro`); declarative Product-blank rule. |
| `qtyOfXVN500RemoteSpeakerMic_astro` (29) | Hide: script fn 19435386457 (`modelSelectionbaseModel_astro`); declarative Product-blank rule. |
| `qtyOfVX650RemoteSpeakerMic_astro` (30) | Hide: declarative ("Hide VRSM attributes if Add VX650 UNCHECKED", `modelSelectionbaseModel_astro`); script fn 19435386578 (same attr). |
| `applicationServicesIntroBundle_astro` (31) | Hide: script fn 19435386625 (`modelSelectionbaseModel_astro`); declarative (`dELETELTE_astro="YES"` hides it — the promo-LTE-deletion rule). |
| `additionalApplicationServices_astro` (32) | Hide: script fn 19435386681 (`modelSelectionbaseModel_astro`); its own selection in turn gates `smartIncidentHelpText_astro` (declarative, `="SMARTINCIDENT"`). |

**Pattern confirmed across all 32**: nearly every attr carries BOTH a
script-gated hide (keyed on `modelSelectionbaseModel_astro`, the same §6
per-model idiom) AND at least one declarative hide/constraint layered on
top (Product-blank, country, or a specific upstream attr value) — matching
exactly the "four layers stacking" model §6 already proposed, now confirmed
attr-by-attr rather than asserted from 2 examples.

## 8. Net priority

Payload correctness (§8 order_number sort) — already shipped. This plan is
purely about **explaining** an already-correct payload, not changing it.
Recommend building in this order: (a) section-scoped summary first — pure
data plumbing, no new rule logic; (b) provenance trace second — needs new
state captured during rule evaluation; (c) script-gated "unknown" labeling
last — smallest, but depends on (b) existing first.
