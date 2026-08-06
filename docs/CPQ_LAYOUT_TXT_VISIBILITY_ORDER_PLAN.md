# CPQ Layout-File Visibility + Order Filter — Plan

Builds on `docs/CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md` (already shipped:
`resolve_ui_layout_scope`/`_detect_layout_tier` read `rule_type=6`
"Configuration Flow" rules + `bm_config_layout_attr_assoc` +
`bm_layout_model` from already-ingested `aryx_entity` data, but that plan's
own docstring flags an **unresolved ambiguity**: APX Next has 4 candidate
`rule_type=6` flows and "this method deliberately does not guess" which
one is the real, currently-active native UI. This plan closes that gap
using the newly-provided layout export, and adds the one signal the
existing relational data does not carry at all: an explicit per-attribute
`hide` boolean.

## 1. What was verified against real data (workspace 3, "Apx Next")

- `Config Layout APX Next.txt` is a decoded native-UI layout export: 347
  leaf components, each a flat `{resourceAttributeVarName, hide,
  resourceAttrType, ...}` object — confirmed one entry per
  `resourceAttributeVarName`, zero duplicates/conflicts.
- **This file IS one of the already-known, already-ambiguous flows** —
  confirmed by exact match, not assumption: the file's own top-level `id`
  (`19435387689`) is byte-identical to one of the 4 `rule_type=6` flow ids
  `resolve_ui_layout_scope(3, "Apx Next")` already returns, and that flow's
  existing `"all"` membership count (347) exactly matches the file's own
  347 leaf entries. The file's `variableName`
  (`configurationFlowForAstroDevicesPortable`) and `status: "Active"` are
  the disambiguating signal the existing mechanism was missing.
- Of the 347, **131 have `hide:false`**; of those, **28 are
  `resourceAttrType: "HTML"`** (page decoration/help text, not a
  configuration input) — leaving **103** real, customer-facing data
  attributes. This `hide`/`resourceAttrType` distinction does **not**
  exist anywhere in the already-ingested relational tables
  (`bm_config_layout_attr_assoc` carries membership + sibling-relative
  `order_number` only; the actual show/hide bit lives in
  `bm_config_layout_attr_prop`'s numeric, undecoded property codes — not
  worth reverse-engineering when the export already hands it to us
  decoded).
- **Ordering**: `bm_layout_model.order_number` is scoped **per parent**
  (sibling position within one section), not a flat document rank —
  confirmed live (`ultimateDestinationCountry`, `hWVersion_astro`,
  `modelSelectionFrequencyBands_astro` all show `order_number: 1`, being
  first children of three different sections). Reconstructing a flat order
  from it needs a full parent-chain tree walk. The .txt file's own nested
  `components.items` array is **already** that exact flattened order — no
  tree walk needed, and confirmed against the running container to be a
  strictly different (and correct) order from either `ConfigAttr.order` or
  the payload's current dependency-topo-sort output.
- **Live end-to-end check** (Region=NA, Country=United States, Product=APX
  NEXT All Band, Hardware Version auto-resolved by rule): today's real
  payload has 82 attributes. Only 40 are in the 103-attribute visible set;
  42 are attributes the layout marks hidden (internal codes, quantity
  flags, `hidddenRecordSeparator_allFamilly`-style separators) that ship
  anyway today. Payload key order does **not** match the layout's order at
  all (spot-checked, confirmed mismatched).

## 2. Design

**Scope of the change: output-only.** `evaluate_rules_loop`, `auto_fill`,
and hiding/recommendation/constraint rule application are **not touched**.
They keep running against the full, unfiltered `attrs`/`filled` exactly as
today — this is the explicit requirement ("rules... triggered properly for
[all] 82 attributes"): many of the 42 layout-hidden attributes are real
rule *inputs* (region/model-selection codes gate other attributes), so
filtering before rule evaluation would silently break cascades. The filter
applies only at the two places output is rendered:

1. **New loader**: `CpqEngine.load_layout_display_order(workspace_id,
   catalog_prefix) -> dict[str, int] | None` — parses the catalog's
   matching layout file once, returns `{variable_name: sequence_rank}` for
   exactly the `hide:false` + non-`HTML` entries, `None` if no matching
   file exists for this catalog (safe no-op fallback — every catalog
   without a layout file, e.g. SL3500e today, behaves exactly as now).
   Cached process-lifetime per `(workspace_id, catalog_prefix)`, same
   idiom as `_LAYOUT_TIER_CACHE`/`_LAYOUT_SCOPE_CACHE`.
2. **File discovery**: match by the catalog's own display name (the same
   string already used as the `source_dataset`/`ontology_type` prefix —
   `"Apx Next"`, `"SVX"`, `"SL3500e"`) as a case-insensitive substring of
   the layout file's name, per the stated convention (an "APX Next" file
   for the APX Next catalog, an "SVX" file for SVX). Directory: proposing
   a new `config_layouts/` folder — **needs your confirmation**, see below.
   Guard: only trust a file whose parsed top-level `status == "Active"`;
   log and skip (fall back to `None`) otherwise, so a stale/deprecated
   export (the `...old` variant confirmed to exist in the raw data) is
   never silently used.
3. **Summary**: `_filled_summary_triples` gets an optional
   `display_order: dict[str, int] | None` param — when set, restrict to
   `var in display_order` and sort by it instead of `display_filled`'s
   fill-order.
4. **Payload**: `build_payload` gets the same optional param, applied as a
   final filter+resort **after** all its existing serialization/hide_in_
   trans/noise/topo-sort logic — the new order wins over the existing
   dependency-topo-sort/`order_number` tie-break, since every attribute
   that survives the filter is, by construction, a real layout member with
   a real rank.
5. Both call sites resolve `catalog_prefix` and call the loader once per
   turn (cached, so effectively free after the first hit per catalog).

**Not in scope here** (flagging, not solving): the ~22 "Required Order
Information" attrs (firstName, contact emails, etc.) that the conversation
never asks for today even though the layout lists them — that's a
separate gap (nothing marks them catalog-required) and is a candidate for
a follow-up, not part of this filter.

## 2b. Extending to question-asking order and rule-conflict order

You asked for two more things to follow the layout file: (a) the order
questions get **asked**, and (b) the order rules get **evaluated**.

**(a) Question-asking order.** Sort `pending_variables` by the same
`load_layout_display_order` rank used for summary/payload. Output-only,
same shape as §2 — doesn't touch `auto_fill`/hiding/recommendation/
constraint evaluation, only which already-pending item gets *asked* first.

**(b) Rule-conflict evaluation order — resolved, using layout order, with
one exemption.** Raised a concern that layout position doesn't track rule
specificity catalog-wide (`hWVersion_astro` sits at layout position 1 —
near the top — despite being a real gating condition for Product
Selection). **You corrected this**: Hardware Version (and any
required/always-directly-asked attribute) is never auto-guessed — its
value is only ever a confirmed client answer by the time any rule
evaluates it, so a rule conditioned on it can't "resolve wrong" regardless
of where it sits in the layout. That exempts required/directly-asked
condition attributes from the specificity concern entirely; the only real
ambiguity is among rules whose conditions are **auto-filled/derived**
attributes competing against each other — checked live and layout order
handles that case correctly (the real `modelSelectionHousing_astro`
conflict: GREEN's condition is `modelSelectionbaseModel_astro`, a
hidden/derived attr at layout position 184; BLACK is script-backed with no
resolvable condition — ranks lowest by construction, so GREEN correctly
wins).

**Adopted rule**: when 2+ rules target the same attribute, rank by each
rule's own condition attribute's layout position — a rule with no
resolvable condition (script-backed, no declarative `conditions`) always
ranks lowest/loses; among resolvable conditions, later layout position
(deeper into the file) wins, since a required/directly-asked condition
never loses on trustworthiness grounds and a derived/auto-filled one's
layout depth is the available specificity signal. Applies to
`apply_recommendation_rules`/`resync_stale_recommendations`
(recommendation) and `apply_hiding_rules` (hiding) — `apply_constraint_
rules` is unaffected (its intersection is commutative, order never changes
its result, confirmed earlier this session). Catalogs with no layout file
keep today's arbitrary-order behavior unchanged (safe fallback, same as
every other layout-dependent piece of this plan).

Sourced from the SAME per-catalog `load_layout_display_order` map as (a)
and §2 — no second data source, no second file-discovery mechanism.

## 2c. Ask only the anchors; skip anything rules can't resolve

Sharpened the conversational flow itself, for catalogs with a layout file:
**only Country, Hardware Version, and Product get asked.** Every other
attribute is either resolved by rules (using the values of those 3 plus
each other, applied in layout order per §2b) or, if nothing resolves it,
**skipped** — never added to `pending`, left entirely absent from
`filled`/`filled_multi` (so it's naturally excluded from the summary/
payload filter in §2 too — nothing to display). Move to the next attribute
in layout order.

**Two exceptions, kept as-is** (confirmed with you — both are real,
live-verified fixes from earlier this session and must not regress):
- **Grid-linked selectors** (e.g. mounting hardware) always ask — never
  auto-filled, never skipped. A wrong guess there is real BOM harm.
- **Sibling-family forced re-asks** (the Frequency Band fix) always ask
  when the governing concept hasn't been confirmed yet, even if nothing
  else would fill it.

**Where this plugs in** — narrower than it sounds, reuses an
already-existing mechanism rather than inventing a new one:
`is_decision_attr` (engine.py `auto_fill`, ~line 5460) is the existing,
already-catalog-agnostic check that currently forces Country/Region,
Hardware Version, and `productSelectionProduct_all` into `pending`
regardless of governance — it already *is* exactly the 3-anchor set. The
final catch-all ask branch (~line 5828: "has options or is a decision attr
→ ask") changes, for catalogs with a loaded layout map only: keep asking
when `is_decision_attr` or `vn in grid_selector_vns`; otherwise, when a
layout map is loaded, skip (no `pending.append`) instead of asking.
Sibling-forced re-asks are a separate code path
(`enforce_exclusive_sibling_families`) and are untouched by this change,
so they keep firing independently. Catalogs with no layout file keep
today's "ask everything with options" behavior, unchanged.

## 2d. Stop filling from default_value / unsatisfied first-available; skip instead

Further tightening, same scope as §2c (**only when a layout map is
loaded** — confirmed with you, to keep the zero-regression-risk shape for
catalogs without a layout file): `auto_fill`'s step 4 (single-select
`default_value`) and the multi-select fallback's `default_value`/
"first-available if genuinely unconstrained" sub-steps no longer fill the
attribute — they skip it (same skip semantics as §2c: absent from
`filled`, not defaulted-empty), unless a recommendation rule's condition
is genuinely satisfied. Net effect: once a layout map is loaded, an
attribute only ever gets a value from (a) a real prior/user answer, (b) an
NL hint, or (c) a genuinely satisfied recommendation rule — never from a
bare catalog default or an unconstrained guess.

**Real-data impact, measured on the same live Example A payload (§4,
40 attributes)**: **32 survive, 8 drop** — every dropped attribute traces
to `filled_source` of `default` or `default_first_available`:
`modelSelectionFrequencyBands_astro`, `antennasType_astro`,
`preSalesEnggAcknowledgement_astro`, `carrierSelectionMultiSelect_astro`,
`selectSecondarySIMCard_astro`, `subscriptionBillingAddDMSCoverage_astro`,
`accessoriesSolutionSet_astro`, `relatedServicesType_astro`. The 32
survivors: 29 genuine recommendation-rule firings (`source=rule`) + 3 real
user/hint answers (Country, Hardware Version, Product) — zero raw catalog
defaults left in the payload.

**⚠️ Same unverified risk as §5, sharper here**: a catalog default often
exists precisely because the real BOM API expects *some* value even when
nobody decided it — that's the entire purpose of a default. Dropping all
8 needs the same live confirm+submit verification against the real
downstream API before trusting this in production; this is a HARD
prerequisite, not optional, given it removes MORE fields than §2's
visibility filter alone ever did.

**Where this plugs in**: the same branches already touched for §2c —
`auto_fill`'s single-select default assignment (step 4, when
`default_value` matches a valid option) and the multi-select fallback's
`default`/`default_first_available` tagging (step 5) — both gated on
`display_order is not None`, mirroring the exact `if display_order is
None or ...: <old behavior> else: skip` shape §2c already established. No
new data source, no new call sites — same `display_order` map already
threaded through `auto_fill`.

## 2e. Rule attribution — record which specific rule fired, not a generic tag

New scope, approved after virtually testing §2d's output against the real
rule trace log (`aryx_rule_trace_entry`, 1,323 real entries for one live
conversation). Finding: today, `auto_fill`'s step 3
(`_satisfied_recommendation`, the mechanism behind every `source=rule`
attribute) only ever logs the generic tag `rule_id="auto_fill:rule"`
(engine.py ~line 5860) — never the specific rule that actually matched.
Cross-checked all 29 real `source=rule` survivors from the Example A
payload against the catalog's own declarative rule conditions: only
**2 of 29** could be attributed this way; the other 27 fire via
BML-script-backed rules (`script`/`condition_script`), which
`_satisfied_recommendation` already evaluates (via `bml_eval`) but
discards the winning rule's identity once it returns.

**Fix**: `_satisfied_recommendation` (engine.py ~line 5242) already holds
the matched `rrule` object at its `if match: return ...` line, for EVERY
path — script, condition_script, and plain declarative. Extend its return
type from `tuple[str, str] | None` to `tuple[str, str, str] | None`,
adding `rrule.rule_name`. Thread that name through the 3 call sites
(~lines 5544, 5798, 5932) into a per-attribute-iteration local, and use it
at the consolidated trace call (~line 5860): `rule_id=matched_rule_name`
when available, falling back to today's generic `f"auto_fill:{source}"`
tag only for the OTHER path into `source=="rule"` (step 5's
`governed_source` branch, which isn't `_satisfied_recommendation`-backed
and has no single rule to attribute). Also switch `rule_type` from
`"auto_fill"` to `"recommendation"` when a specific rule is attributed —
lands these entries in the SAME query bucket `apply_recommendation_rules`'
own trace entries already use, so one query answers "which rule fired
this attribute" regardless of which of the two mechanisms actually fired
it.

**Deliverable this unlocks**: a per-payload attribution report — for each
of the 32 (or however many) final attributes, the specific rule name (or
"direct user/hint answer" for the 3 anchors) that produced its value,
built by joining `build_payload`'s output keys against
`aryx_rule_trace_entry` filtered to `rule_type IN ('recommendation',
'hiding', 'constraint')` for that `run_id`, keeping the last fire per
attr. Not a new UI feature by itself — the query/report itself is a small
follow-up once the trace data is actually there; flagging it as a known
next step in Not in scope below rather than open-ended scope creep here.

**Not in scope here**: building a user-facing attribution report/endpoint.
This section only fixes the underlying trace data to make one possible —
matches this plan's own pattern of separating "make the signal available"
from "build a feature on top of it" (see §2's own "Not in scope" note on
Required Order Information).

## 2f. Eliminate the THIRD blind-fill path — governed default-or-first

§2d closed two blind-fill paths (bare `default_value`, unconstrained
multi-select first-available). Live-verified §2e's own output exposed a
**third, separate** one: of the 33 real `source=="rule"` attributes in
the Example A payload, only 9 trace to an actually-satisfied
recommendation rule (§2e) — the other **24** trace to `auto_fill`'s
*governed default-or-first* fallback (engine.py ~line 5867: "single/
boolean, 2+ options, no default: first by menu order... safe here because
a rule REQUIRES this attr to be resolved") and its sibling for governed
booleans with no menu at all (~line 5876: bare `value = "false"`). Both
fire whenever an attr is merely *governed* (some rule somewhere targets
it) but no rule's condition actually holds right now — "rule requires
this resolved" turns out to mean "some rule cares about this attr in
general," not "a rule has decided its value" — the exact same blind-guess
shape §2d already eliminated elsewhere, just a third code path carrying
it.

**Confirmed against the real trace log, not assumed**: checked all 22 of
these attributes' full trace history for this run — **zero** have any
`hiding`-type entry at all. No hiding rule is silently failing to fire for
them; there simply is no rule-driven signal (recommendation or hiding)
backing any of these 22 today. Under your instruction ("no default or
first mechanism... selected by rules/recommendation or hidden by hiding
rules"), all 22 would be **skipped** — same semantics as §2c/§2d, gated
the same way (`display_order is not None` only).

**Real-data impact**: Example A's 37-attribute payload → **15**
(37 − 22). This is the largest single cut in the whole plan — confirm
before implementing:

| Step | Payload size |
|---|---|
| Today (no plan) | 82 |
| §2 (visibility filter) | 40 |
| §2d (no bare default/first-available) | 37 (this run's real number, differs from earlier examples by conversation content) |
| §2f (no governed blind-fill either) | **15** |

**⚠️ Sharpest version yet of the §5/§2d downstream-API risk**: at 15
attributes, the payload is now overwhelmingly just the 3 anchors +
whatever a small number of rules actually fired + grid selectors/sibling
re-asks. If the real BOM submission API has ever silently relied on any
of these 22 fields being present (even a bland default), this is where
it would break first. The live confirm+submit verification called out in
§5/§2d is now a **hard blocker**, not a nice-to-have, before this piece
ships to production — recommending §2f ship separately/behind additional
confirmation from §2/§2d, not bundled into the same release.

**Where this plugs in**: same `display_order is not None` gate, applied
to the two branches above (engine.py ~5867 and ~5876) — no new call
sites, no new data source.

## 2g. Narrow carve-out: use default_value only when it survives an active constraint

Live discovery, found while verifying §2f against a real "APX NEXT Single
Band" order: `modelSelectionFrequencyBands_astro` has a real, currently-
active **constraint** rule ("Constrain for APXNEXTSINGLE &
APXNEXTXNSINGLE") narrowing it to 3 genuinely different, valid options
(`UHF`, `VHF`, `700/800 MHz`) — a real hardware decision (different
physical radios) — but **no recommendation rule ever picks between them**.
Under §2f this silently skips.

Considered asking in this case (a real decision, nothing backing it);
**you overruled that** — skip stays skip even when nothing resolves it.
The only thing that changes: if a real `default_value` happens to also be
one of the currently-valid (constrained) options, use it. Final,
simplified rule:

1. **Constraint active + no recommendation + `default_value` is one of
   the currently-valid options** → **fill it**. Different from what §2d
   eliminated: §2d's target was a *bare* default with zero constraint
   context (never confirmed to survive a product-specific narrowing);
   this one has *already been confirmed* valid under the exact constraint
   active right now.
2. **Everything else** — constraint active with no surviving default, or
   no constraint at all — **skipped**, per §2f, unchanged.

No "ask" path in this section at all — that idea was raised and
explicitly rejected.

**Real-data impact, measured** — replayed the real "APX NEXT Single Band"
order and cross-checked the actual trace log + real `default_value`
column for all 5 real candidates §2f would otherwise skip:

| Attribute | Valid options | `default_value` | Outcome |
|---|---|---|---|
| `modelSelectionFrequencyBands_astro` | UHF, VHF, 700/800 MHz | "700/800 MHZ" (valid) | **filled** |
| `antennasType_astro` | Whip APX Next, No Antenna | "WHIP APX NEXT" (valid) | **filled** |
| `additionalSystemEnhancementFeatureType_astro` | 9 options | *(none)* | skipped |
| `dMSDurationYears_astro` | 5/3/7 Years | *(none)* | skipped |
| `serviceTypeAdditionalDMSCoverage_astro` | Essential / No Essential-Standard Warranty Only / Essential w Accidental Damage | *(none)* | skipped |

Net: of the 5, **2 get filled, 3 stay skipped** (not asked). Product-
specific, not a universal constant, same caveat as before.

**Where this plugs in**: same branch as §2f (engine.py ~5867).
`valid_opts` (already computed) and `constrained_opts.get(attr.entity_id)
is not None` (active-constraint check) are both already local. Add: when
a constraint is active and `len(valid_opts) >= 2`, check whether
`attr.default_value` matches one of `valid_opts`; if so, fill it
(`source = "default"` — same well-defined, catalog-sourced meaning as
today's default-fill, now additionally confirmed constraint-valid);
otherwise fall through to §2f's existing skip. No new data source, no
new call sites, no change to `pending` at all.

## 3. Where layout files live — local today, cloud-ready by design

You want today's answer to be "current directory" without locking the
design to it — the same "swap the backend later without touching the
callers" shape this codebase already uses for secrets
(`src/aryx/broker/secrets.py`: a `SecretProvider` `Protocol`, a
no-dependency `EnvSecretProvider` default, and an `AwsSecretProvider` that
lazy-imports `boto3` only when actually selected). Reusing that exact
pattern here instead of inventing a new one:

- **`LayoutFileSource` (Protocol)** — one method,
  `get(catalog_name: str) -> str | None` (the raw file text, matched by
  the catalog-name-substring convention from §2; `None` if no file for
  that catalog — safe no-op, same as everywhere else in this plan).
- **`LocalDirLayoutFileSource`** (the default, zero extra dependencies) —
  scans a configured directory for a filename containing `catalog_name`.
  Directory comes from an `ARYX_CPQ_LAYOUT_DIR` env var, **defaulting to
  the repo root** — matches "right now it will be in current directory"
  exactly, with the path already externalized so moving the directory
  later (still local) is a config change, not a code change.
- **Future: `CloudLayoutFileSource`** (e.g. S3/Azure Blob/GCS) — same
  `Protocol`, lazy-imports its SDK exactly like `AwsSecretProvider` does,
  takes a bucket/container + prefix instead of a directory. Not built now
  — the point of the Protocol is that adding it later is a new ~20-line
  class, not a rewrite of `load_layout_display_order` or either call site.
- **Selection**: whoever constructs `CpqEngine` passes the source in (or
  omits it for the `LocalDirLayoutFileSource` default) — same
  dependency-injection shape as `SecretProvider`, no env-var-driven
  if/elif chain buried in the loader itself.
- Still **not** routed through the landed-record ingestion pipeline —
  that pipeline's own `aryx_entity` data is missing exactly the `hide` bit
  this file supplies (§1), so ingesting through it would gain nothing
  regardless of where the file physically lives.

## 4. Worked examples — real, live-verified, not hypothetical

Both driven against the running container (workspace 3), Region=NA,
Country=United States, differing only in Product. Numbers are the actual
predicted output of §2+§2b+§2c applied to real payloads pulled from the
live conversation, not a mockup.

**Example A — Product = APX NEXT All Band.** Today's real payload: 82
attributes, arbitrary order. Under the plan: **40 attributes**, in the
file's order, grouped by real section (Geography → Product Selection →
Model Selection → Language → ... → Related Software And Services
Filters). Full predicted JSON and grouped summary already produced and
reviewed in-session.

**Example B — Product = APX NEXT XE All Band** (same Region/Country).
Today: 83 attributes. Under the plan: **41 attributes** — same shape as A,
with real XE-specific differences correctly carried through:
`modelSelectionHousing_astro → Black`, `beltClipType_astro → Plastic Carry
XE Holster With 3 Inch Clip`, `packingPackageType_astro → Bulk XE`.
Confirms the filter/reorder generalizes across products, not tuned to one.

**Negative results — checked, not assumed, and both matter:**
- *Rule-conflict path (§2b) did not fire in either example.* Housing's
  "GREEN" rule needs Display Type=Touch Screen **and** Base Model ∈
  {H45TGT9PW8AN, H55TGT9PW8AN, H55TGU9PW8AN}. Example B resolved Display
  Type=Limited Keypad, Base Model=H45TGU9PW8AN (a different real SKU — one
  letter off, U vs T) — GREEN's condition genuinely doesn't hold, so BLACK
  is objectively correct under both today's arbitrary order and the plan's
  layout-position ranking. The two rules only conflict in the abstract;
  their real trigger conditions rarely overlap in practice. The ranking
  logic is still needed for whenever they DO overlap (unverified live, but
  provably possible from the rule definitions themselves) — this doesn't
  weaken the case for §2b, it just means it's a rarer live event than the
  static rule audit suggested.
- *Skip-if-unresolved path (§2c) did not fire in any of 3 real products
  tried* (All Band, XE All Band, International/Federal) — `pending` always
  reaches empty; every attribute got a real rule/default value. This
  catalog's auto-fill coverage (partly a result of this session's own
  earlier fixes) is comprehensive enough that "nothing can resolve this"
  is rare here. §2c remains a correctness safety net — needed for less-
  covered configurations, edge-case combinations not yet tried, or other
  catalogs with sparser rule authoring — not something that visibly
  changes output for the common paths tested so far.

## 5. Impact

**Payload size**: -51% to -52% in both real examples (82→40, 83→41).
Every dropped attribute is either layout-internal (quantity/array
plumbing, separators, region/model codes real customers never see) or an
integration/system field — none are customer-meaningful data lost from
the *summary*.

**⚠️ Unverified risk, called out rather than assumed away**: dropping
those same 42/42 attributes from the *payload* has only been checked
against the native UI's own visibility signal (`hide`), never against
whether the downstream BOM submission API structurally requires any of
them regardless of display. `build_payload` already excludes some fields
today (`hide_in_trans=1`, noise vars) specifically because "the real API
rejected them" — a *precedent* for real API-shape sensitivity, not proof
either way for this new set. Before this ships, a real `confirm` + submit
run (not just `show me the json`) against whatever the BOM API actually
validates against needs to happen — recommending this as a **hard
prerequisite to enabling §2's payload filter in production**, independent
of the summary-only piece (§2 summary filtering carries no such risk — it
never touches what gets submitted).

**Conversation length**: potentially large reduction for catalogs with a
layout file — from however many attributes currently reach `pending`
today down to effectively 3 (+ any grid selectors hit) per §2c. Not
observed live yet (all 3 real products tried already auto-resolved fully
before this piece would even activate) — the size of this benefit is
real but currently unmeasured on this catalog.

**Blast radius**: every mechanism is gated on a loaded layout map being
present for the catalog in play. SL3500e and any other catalog without a
file keep 100% of today's behavior — zero risk of regression there. Within
APX Next, §2/§2b/§2c are three independent toggles sharing one data
source; each could ship separately if you want to de-risk further (e.g.
ship §2's display-only filtering first, hold §2c for a second release
once the payload-API risk above is closed out).

## 6. Testing plan

- Unit tests for `load_layout_display_order`: valid file → correct
  filtered/ordered map; `status != "Active"` → `None`; no matching file →
  `None`; malformed JSON → `None`, logged, never raises.
- `_filled_summary_triples`/`build_payload` with `display_order` supplied:
  confirm filtering to exactly the visible set and correct resulting
  order, on a small synthetic fixture.
- `pending_variables` ordering: synthetic fixture with 3+ pending attrs in
  a deliberately-scrambled fill order, assert they get asked in layout
  order once a display_order map is supplied; no layout map → unchanged
  (today's) ordering.
- Rule-conflict ranking: synthetic fixture reproducing the
  Housing/Base-Model/BLACK-GREEN shape — one declarative rule with a
  resolvable, deep-position condition vs. one script-backed rule with no
  condition, both targeting the same attr; assert the declarative rule
  wins under both raw input orders. A second fixture with 2 declarative
  rules at different condition positions targeting the same attr; assert
  the later-position one wins, both raw orders. A third fixture where the
  higher-ranked condition attr is itself `required` (directly-asked);
  assert it still wins purely on position — the exemption in §2b means its
  value is never in question, not that it's disqualified from ranking.
- Regression: existing summary/payload/hiding/recommendation tests
  unchanged (new ranking only activates when a layout map is present and
  a real same-target conflict exists — re-run
  `test_cpq_recommendation_respects_active_constraint.py` and the hiding-
  rule suite to confirm zero behavior change without a layout file).
- Live replay: rerun the exact Region/Country/Product/Hardware-Version
  conversation against the container; confirm the JSON payload has
  exactly the 40 attributes from §1 (or whichever subset a fully-answered
  session resolves to), in the file's order, questions get asked in layout
  order, and any real Housing-style conflict resolves to the
  higher-layout-position rule's value.
- Ask-only-anchors / skip-if-unresolved (§2c): synthetic fixture with a
  layout map loaded, one decision attr (e.g. Country), one grid-linked
  selector, one sibling-forced-reask, and one plain rule-governed attr with
  NO applicable rule/default; assert only the first three land in
  `pending` and the fourth is entirely absent from `filled`/`pending`
  (skipped, not defaulted-empty). A second fixture with no layout map
  loaded: assert the plain attr IS asked (today's unchanged behavior) —
  proving this is strictly additive, gated on layout-map presence. Live
  replay: confirm the container only ever asks about Region/Country/
  Product/Hardware Version (+ any grid selector encountered) for the APX
  Next flow once wired, and that every other attribute in the final
  payload traces to a real rule/default, never a bare unfilled ask.

### Concrete test cases from the two worked examples (§4)

These pin the exact real numbers/values from §4 as recorded-fixture
regression tests (real `filled`/`filled_multi` snapshots captured from the
live container, replayed offline — no network dependency in CI):

1. **`test_layout_filter_example_a_all_band`** — feed the real Example A
   `filled`/`filled_multi`/`attrs` snapshot (Product=APX NEXT All Band)
   into `build_payload(..., display_order=load_layout_display_order(3,
   "Apx Next"))`. Assert: `len(configData) == 40`; first 3 keys are
   `ultimateDestinationCountry`, `hWVersion_astro`,
   `productSelectionProduct_all` in that order; all 42 real dropped keys
   (`hidddenRecordSeparator_allFamilly`, `packageRegion`,
   `modelSelectionRegion_astro`, `validationOrg`, ... — full list already
   enumerated in-session) are absent.
2. **`test_layout_filter_example_b_xe_all_band`** — same shape, Product=APX
   NEXT XE All Band snapshot. Assert `len(configData) == 41` and
   `configData["modelSelectionHousing_astro"]["displayValue"] == "Black"`,
   `configData["packingPackageType_astro"]["displayValue"] == "Bulk XE"`
   (the two real XE-specific values found live) — catches any future
   regression that accidentally hardcodes example A's values instead of
   genuinely reading from `filled`.
3. **`test_layout_filter_summary_matches_payload_membership`** — for both
   snapshots, assert `_filled_summary_triples(..., display_order=...)`
   returns exactly the same 40/41 variable_names as `build_payload`'s keys
   (same filter, two call sites, must never drift apart) and in the same
   relative order.
4. **`test_housing_conflict_does_not_fire_for_example_b`** — regression
   pin for the negative result: assert Example B's real conditions
   (`modelSelectionDisplayType_astro == "Limited Keypad"`,
   `modelSelectionbaseModel_astro == "H45TGU9PW8AN"`) make GREEN's
   condition evaluate false, so ranking never even has to choose — Housing
   resolves to BLACK regardless of rule order. Paired with the earlier
   synthetic conflict tests (which force GREEN's condition true) so both
   the "doesn't fire" and "does fire and resolves correctly" cases are
   covered from real data, not just synthetic extremes.
5. **`test_no_pending_attrs_beyond_anchors_for_three_real_products`** —
   parametrized over the 3 real product snapshots tried (All Band, XE All
   Band, International/Federal); with §2c wired, replay each and assert
   `pending_variables` never contains anything outside
   {`modelSelectionRegion_astro`, `ultimateDestinationCountry`,
   `productSelectionProduct_all`, `hWVersion_astro`} ∪ any grid-selector
   vns for that product — documents today's confirmed-empty skip rate as
   an explicit, checked baseline rather than an assumption.
6. **`test_layout_example_a_default_and_first_available_attrs_are_dropped`**
   (§2d) — recorded-fixture test using the same Example A snapshot as #1:
   assert `build_payload(...)`'s `configData` has exactly **32** keys
   (down from 40), and that all 8 named attrs above
   (`modelSelectionFrequencyBands_astro`, `antennasType_astro`, ...) are
   absent. A companion synthetic fixture with `display_order=None` asserts
   the SAME 8 attrs are still filled via default/first-available exactly
   as today — proving §2d is strictly additive, gated on the layout map.
7. **`test_satisfied_recommendation_still_fills_under_2d`** — synthetic
   fixture: an attr with no default_value but a recommendation rule whose
   condition genuinely holds; assert it's still filled (source=`rule`),
   confirming §2d only removes the default/first-available sub-steps, not
   genuine rule-driven resolution.
8. **`test_satisfied_recommendation_returns_rule_name`** (§2e) — synthetic
   fixture with a plain declarative recommendation rule; assert
   `_satisfied_recommendation` now returns `(item_value, display_name,
   rule_name)` and the rule name matches the fixture's own `rule_name`.
9. **`test_satisfied_recommendation_returns_rule_name_for_script_rule`**
   (§2e) — same, but for a `script`-backed and a `condition_script`-backed
   rule (mocked `bml_eval`); confirms attribution works for the 27-of-29
   real majority case, not just the 2-of-29 declarative minority already
   traceable today.
10. **`test_auto_fill_traces_specific_rule_name_not_generic_tag`** (§2e) —
    drive `auto_fill` end-to-end with `rule_trace` bound (test context) and
    a satisfied recommendation rule; assert the recorded trace entry has
    `rule_type="recommendation"` and `rule_id=<the real rule name>`, not
    `rule_type="auto_fill"`/`rule_id="auto_fill:rule"`. A second case (the
    step-5 `governed_source` path, no single attributable rule) asserts
    the generic tag is still used there — proving the fallback still
    covers the one case with genuinely no single rule to name.
11. **Live regression check**: replay Example A/B against the container
    post-change, re-run the exact `aryx_rule_trace_entry` query from this
    session's live investigation, and confirm the count of attributable
    (`rule_type='recommendation'`, real rule name) entries among the 29
    real `source=rule` survivors rises from 2 to (ideally) all 29 — any
    still stuck on the generic tag should be individually explainable
    (e.g. a genuinely unresolvable script), not silently unfixed.
