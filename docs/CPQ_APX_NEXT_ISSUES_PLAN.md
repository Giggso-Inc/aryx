# APX Next Issue Report — Root Causes & Fix Plan

**Status:** All 10 audit queries run live against workspace 13
(`aryx_ws_13`, 46,498 entities / 49,165 edges). Every root cause below is
either code-confirmed, live-data-confirmed, or explicitly identified as a
BM source-catalog gap — nothing left as "pending."
**Date:** 2026-07-10
**Depends on:** `docs/CPQ_GRAPH_FIX_PLAN.md` §6a and
`docs/CPQ_CASCADE_CONVERSATION_PLAN.md` Phases A–F (already implemented,
merged to `dev`) — this plan extends and closes gaps in that same engine.
**Sample:** `APX_Next_config.xml` (427 config attrs, 688 rules, 923 BML
scripts, 457 `bm_config_marked_attr` rows — far richer than the SL3500e dummy
file), ingested as workspace 13. All live queries in this doc ran directly
against that workspace's FalkorDB graph; nothing here hardcodes values —
every number is a live count, quoted for evidence, not asserted in test code.

---

## 1. Issue report (as received)

> **CRITICAL ETL BUG:** FalkorDB extraction for APX Next is broken.
> `ApxNextConfigBmConfigRuleAction` nodes are missing their payload
> logic/BML scripts and only store UUIDs in the name field. Relationship
> edges between `ApxNextConfigBmConfigAttr` and Rule/Action nodes were not
> generated. Menu items for dynamic constraints (e.g. "LTE CAPABILITY NO
> SERVICE") were not extracted.
>
> **Conversational/logic issues:** failed context extraction (ignores
> upfront constraints like "US customer"), interrogation fatigue (23-question
> linear loop instead of applying CPQ defaults), LTE/Carrier state conflict
> (no state — allows an active carrier on a radio with deleted LTE),
> hardware double-charging (overlapping accessory fields let two conflicting
> surveillance kits get selected), disconnected database (diagnostic graph
> appears empty). Client-provided input must be re-validated against rules,
> not re-asked (e.g. US customer → default region, don't ask region again).
> Hidden-rule-driven dependent variables should not appear in verbose output.

Live ingestion log surfaced during this investigation (job
`98056bee668541a5b926da89c95a4d28`, `152 checks, 147 pass, 3 fail, 1 warn, 1
skip`) — three `fk_coverage` failures, analyzed in §3 below.

---

## 2. Findings — ETL bug re-examined

### 2a. "UUIDs in the name field" — cosmetic, not a bug

Verified directly against the raw XML: `bm_config_rule_action` elements
genuinely carry **no `name` field** in Oracle CPQ's own source data (checked
923 real actions). The action's actual logic — `function_id`,
`attribute_id`, `action_type` — **is** correctly extracted; nothing is lost.
Downstream, `display_name()`/`_alias_name()` falls back to `guid` (a UUID)
because no better candidate field exists. Nothing to fix in extraction; a
synthetic label (e.g. `"Action on {attribute}"`, derived from the already-
extracted `attribute_id` + `action_type`) would improve *display* only.

### 2b. Missing REL edges — real gap, root cause confirmed twice (static + live)

`_detect_fk_links` (`doc_discovery.py:598-703`, three passes) is the code
that decides which relationship edges get written during ingestion. Traced
against real data twice:

- **Static (before live log):** `bm_config_rule_action.attribute_id` should
  link to `bm_config_attr.id` — Pass 1 requires an exact match against
  `tag_word` (`doc_discovery.py:619`, only the **last** CamelCase word of the
  target type, e.g. `"attr"` for `BmConfigAttr`). `"attribute_id"` != any of
  `attr_id` / `bmconfigattr_id` — no match. Pass 2 explicitly skips because
  the target's match key is bare `"id"` (below its 3-char stem floor,
  `doc_discovery.py` Pass 2 docstring).
- **Live, from your ingestion log — same mechanism, three more columns:**

  | Column | Target type | `tag_word` (last word only) | Why it misses |
  |---|---|---|---|
  | `attr_set_id` | `BmConfigAttrSet` | `"set"` | real column has an `attr_` prefix the heuristic never sees |
  | `page_template_id` | `BmConfigPageTemplate` | `"template"` | `page_` prefix invisible |
  | `config_attr_id` | `BmConfigAttr` | `"attr"` | `config_` prefix invisible |

  All three: `expected` (the validator's own, more permissive tag-suffix
  match) is nonzero (67, 1, 1) while `actual` (edges actually written) is 0.
  Confirmed via `git`-traced code (`doc_discovery.py:626-636`,
  `ingest_validation.py:144-177`), not guessed.

**The `dangling_fk_values=1 sample=['-1']` in the same log lines is a
separate, cosmetic issue** — BigMachines' universal "not set" sentinel
(`-1`) gets counted as a broken reference by `ground_truth_from_tabular`
(`ingest_validation.py:168-176`, no `-1`-exclusion), inflating the apparent
problem count without indicating real data loss.

### 2c. Menu items not extracted — REFUTED against live data

Audit query #4, run verbatim against workspace 13:
`carrierSelectionMultiSelect_astro` → 6 real menu items including
**"LTE CAPABILITY NO SERVICE" at order 6** — the exact value the report
named as missing. Menu-item extraction is working correctly; this was not
a real gap.

### 2d. "Disconnected database — completely empty" — REFUTED against live data

Workspace 13's graph has **46,498 entities and 49,165 REL edges**, with
every expected APX Next type present at counts matching the raw XML almost
exactly (e.g. 923 `BmFunction`, 688 `BmConfigRule`). The graph is not empty.
Most likely explanation: whatever diagnostic tool produced this claim was
either pointed at a different/wrong workspace, or checked before this
ingestion run completed — not a regression in Aryx's own pipeline.

---

## 3. Findings — conversational/logic issues

### 3a. Interrogation fatigue — downstream symptom of §2b, not independent

`auto_fill`'s default-value step (`engine.py`, priority 2) applies
unconditionally regardless of rule governance; the rule-governed
default-or-first step (D2, already shipped) only helps attrs that are
targets of a *resolved* rule. If §2b's linkage gaps mean fewer of APX Next's
688 rules resolve into usable `HidingRule`/`RecommendationRule`/
`ConstraintRule` objects than should, fewer attrs become eligible for
auto-fill — the question count inflates as a side effect. **Fix §2b-class
gaps first, re-measure the question count after — do not treat this as a
separate bug requiring its own fix.**

### 3b. "Validate input against rules again" — confirmed, serious, independent bug

`apply_answer(attr, user_answer)` (`engine.py:1526`) matches the user's
typed reply against the attr's **full, unconstrained option list** — it has
no `constrained_opts` parameter at all, and its only call site
(`ask_api.py:608`) passes no constraint filtering either. A user who types
an out-of-region value that happens to text-match *some* menu option gets
it locked in regardless of what the active constraint rules currently
allow. This is the direct mechanism behind "illegal regional mismatches" —
confirmed by reading the function signature and its call site, not
inferred from the symptom.

### 3c. LTE/Carrier "lacks state" — TWO confirmed causes, one code gap + one source-data gap

**Code gap (fixable, §3c-i):** `auto_fill` (`engine.py:1052`, the
`if vn in filled: ... continue` block) unconditionally skips re-checking an
**already-filled single-select** value against a freshly recomputed
`constrained_opts`. Phase D built this exact re-validation for multi-select
(`dropped_multi`) but never extended it to single-select.

**Source-data gap (traced by id, live — §3c-ii, likely not fixable in
Aryx):** Audit queries 6/7 returned zero rows, but **not** because the
rule→input/action relationship is missing — 6,217 real `REL` edges touch
Rule nodes. The zero rows happened because the audit queries search
`name CONTAINS 'delete lte'`/`'carrier'`, and `name` is a UUID for these
node types (§2a). Tracing by **attribute id** instead (the way the live
engine actually resolves rules) found the real chain: Delete-LTE (`src_id
22194395467`) triggers 6 real rule inputs, one of which (`rule
22194396172`) targets `wirelessCarrier_astro` — **not**
`carrierSelectionMultiSelect_astro`, the attr that actually carries the
"LTE CAPABILITY NO SERVICE" option. Its action's BML script:

```
retVal = "";
if(not isnull(usersessionget("TE_FLAG"))) {
  setValResp = util.setConstraintValuesInSession("wirelessCarrier_astro", retVal, "DISALLOW");
}
return retVal;
```

This disallows an **empty string** on a **different, legacy carrier attr**,
gated behind a session flag (`TE_FLAG`) that's never set anywhere in this
export. Directly confirmed: `carrierSelectionMultiSelect_astro` (the real,
LTE-NO-SERVICE-bearing attr) has **zero** rule inputs referencing
Delete-LTE at all — the constraint the report describes does not exist for
the attr the user actually sees. **This is a BM source-catalog authoring
gap** (an incomplete/legacy rule), not an Aryx extraction bug — §3c-i's fix
makes state changes stick once a rule fires, but no rule ties these two
attrs together in the source data as it stands.

### 3d. Hardware double-charging — CONFIRMED as a genuine BM source-catalog gap, not an Aryx bug

Traced by id (live, workspace 13), same rigor as §3c: `spSurveillancePackagesTypes_astro`
(plural, the multi-select variant) has 6 real rule_actions governing it —
correctly rule-driven. `spSurveillancePackagesType_astro` (singular, the
single-select variant) has **zero rule_actions AND zero rule_inputs** —
confirmed by direct query, it is not referenced by any rule in either
direction. It is a fully freestanding, always-visible, always-asked
attribute with a real duplicate that IS properly governed. **This settles
the (a)/(b) question from the original plan: (b) is confirmed** — no hiding
rule was ever authored to suppress the redundant singular variant. §2b's
FK-detection fix cannot resolve this because there is no missing edge to
detect; the relationship genuinely does not exist in the source.

**Decision needed:** either (i) flag this to the BM catalog owner as a
data-quality gap (no code change), or (ii) build the previously-deferred
name-similarity heuristic (detect same-concept attrs differing only by
`select_type`/naming and treat them as mutually exclusive) as a new,
Aryx-side safety net for catalogs with this class of gap. (ii) is real new
scope — flagging as a proposal below, not assuming it's wanted.

### 3e. Verbose mode shows system/internal noise — confirmed, fix scope widened by live data

`render_filled_summary` (`engine.py:1620`) filters only HTML-template
values — confirmed. Query #9 run live against workspace 13 (its own
`hidden='0' AND NOT variable_name STARTS WITH '_'` filter) returned
`CRM_BILL_COUNTRY`, `CRM_CUSTOMER_ID`, `CRM_BUYER_COMPANY`, etc. at the
**top** of the "clean" list — proving the underscore-prefix rule alone is
**not sufficient**: `CRM_*`-prefixed integration fields pass it and would
still clutter a sales-rep summary. Query #10's aggregate (121 system-hidden
/ 306 user-facing / 427 total) is a useful health-check number, but the
"user-facing" bucket as defined by the query still includes this CRM noise.
**Fix scope widened:** exclude both underscore-prefixed *and*
integration-prefix patterns (derived generically — any variable_name whose
stem matches a small set of known CRM/system prefixes present in the data,
not a hardcoded list of THESE specific names) from the verbose narrative.

### 3f. "US customer → don't ask region again" — mechanism correct, but confirmed ungoverned for APX Next

Phase B's `apply_recommendation_rules` fires regardless of governance
whenever its condition is met (country=US → region=NA) — the mechanism is
correct. **Live-checked this round:** after resolving product+country on
workspace 13, `modelSelectionRegion_astro` and `packageRegion` are both
still pending, and both are confirmed **ungoverned** (zero rule_input,
zero rule_action references — same evidence method as §3d). No
country→region recommendation rule exists in APX Next's catalog. Same gap
class as §3c-ii/§3d: a BM source-catalog authoring gap, not an Aryx defect.
§4's new Phase N (below) is what actually closes this for the 2–3-prompt
target — not a rule fix, since there is no rule to fix.

### 3g. New client spec: ≤2–3 prompts end-to-end — approved decision, widens D2's eligibility rule

**Spec (as given):** seed with product, prompt for country only if not
already given, then auto-fill everything else by default-or-any-value
(cascading through hidden/constraint/recommendation rules), surface only
"important" (rule-governed) attrs in verbose, JSON only on request and
containing everything, and a value change must cascade-recompute all
dependents using the same auto-fill rule — target ≤2–3 total prompts.

**Live-verified before any decision was made (workspace 13, real
conversation via `_run_cpq_turn`):**
- "Skip country if given upfront" already works correctly — one message
  ("Quote APX Next for a US customer") resolves both anchors with zero
  extra prompts, `pending_anchor` clears, `country` is captured directly.
- After that, **29 attributes remain pending.** Cross-checked against
  `governed_target_ids()`: only **1 of 29** is rule-governed — Phase G's FK
  fix alone cannot get this catalog anywhere near 2–3 prompts.
- All **29 of 29** pending attrs are `required=False` in Oracle CPQ's own
  source data — none are source-flagged mandatory. Only 2 are decision-key
  (`modelSelectionRegion_astro`, `packageRegion`).

**Decision (approved):** widen D2's auto-fill eligibility test. An attr is
now eligible for default-or-first auto-fill if **EITHER** (a) it's
rule-governed (existing D2, unchanged), **OR** (b) `required == False` in
its own source data — **excluding** decision-key attrs (`country`/`region`,
`_DECISION_REQUIRED_KEYS`) either way. Rationale: Oracle CPQ's own
`required` flag is a source-authored safety signal, not an Aryx guess — a
materially different risk profile than Issue 6's original "guess a
mandatory technical spec" failure mode. Live-simulated: this resolves
APX Next's 29 pending attrs down to the 2 region-related ones — landing at
2–3 total prompts (product+country combined, then region), matching the
target.

**Explicit residual risk, not eliminated:** if CPQ's own `required=False`
flag is stale/wrong for some attr, that attr now gets a silently-picked
value — bounded in scope (a source-flagged-safe subset) but not zero risk.

---

## 4. Fix plan

```
Phase G — FK-detection compound-column fix (§2b)     — IMPLEMENTED — doc_discovery.py _detect_fk_links Pass 1 now checks every trailing-word-run suffix of the de-camelCased type name, not just the last word; verified against all 3 live-failing columns (attr_set_id, page_template_id, config_attr_id)
Phase H — dangling-FK sentinel exclusion (§2b cosmetic) — IMPLEMENTED — ingest_validation.py ground_truth_from_tabular skips "-1" before dangling/resolvable classification
Phase I — apply_answer constraint validation (§3b)   — IMPLEMENTED — engine.py apply_answer gains constrained_item_values; ask_api.py Step 5 recomputes constraints from session.filled (pre-answer state) via a bml_eval hoisted earlier in _run_cpq_turn
Phase J — single-select re-validation (§3c-i)        — IMPLEMENTED — engine.py auto_fill's already-filled branch re-checks constrained_opts, clears+reports via the same dropped_multi-style dict on mismatch, falls through to re-resolution (inherits Phase N's widened eligibility automatically)
Phase K — verbose summary noise filter (§3e) + Key-decisions grouping (§3g) — IMPLEMENTED — engine.py render_filled_summary: generic structural noise filter (_is_noise_var: underscore-prefix or ALL-CAPS leading segment) + optional rule_governed_ids split into "Key decisions" vs "+N other field(s)"
Phase L — live audit against workspace 13 — COMPLETE — all 10 queries run, findings folded into §2/§3 above
Phase M — surveillance/carrier mutex decision (§3c-ii, §3d) — HITL: flag-to-catalog-owner vs. build a mutex heuristic — NOT YET RESOLVED, awaiting user response
Phase N — widened auto-fill eligibility for ≤2-3-prompt target (§3g) — IMPLEMENTED — engine.py: governed_target_ids widened, new rule_governed_ids() extracted, auto_fill tags filled_source "rule" vs "optional"

G/H/I/J/K/N are implemented in code as of this pass (engine.py, ask_api.py,
doc_discovery.py, ingest_validation.py); tests/test_cpq_e2e.py::test_s9 was
updated for Phase N's new semantics. S15-S26 (the new scenarios below) are
still specified but NOT yet written as test code — the phases are verified
so far by full-suite passes (`PYTHONPATH=src python -m pytest
tests/test_cpq_e2e.py`, 12 passed / 1 skipped / 1 pre-existing unrelated
failure) plus targeted manual reasoning per phase, not yet by dedicated
regression tests. M remains open.
```

**Sequencing:** G and H are independent, land together (`doc_discovery.py`
and `ingest_validation.py`, no shared code). I and J are independent of each
other and of G/H — both are pure `cpq/engine.py` fixes with no ingestion
dependency, land immediately. K is a small, isolated fix, any time. **L is
done** — every finding above came from it. **M is a decision, not code** —
see §3d/§3c-ii; do not start building a heuristic before this is resolved.

### Phase G — FK-detection compound-column fix

Extend Pass 1's candidate set beyond `tag_word` (last word only) to also
check the **full de-camelCased tag** (e.g. `"attrset"`, `"pagetemplate"`)
and, generically, any suffix of the type's de-camelCased name — not just
the last word. Must stay allowlist-free and derived purely from the type
name, per the project's no-hardcoding discipline. Verify against APX
Next's exact three failing columns (§2b table) before calling this closed.

### Phase H — dangling-FK sentinel exclusion

`ground_truth_from_tabular` (`ingest_validation.py:168`) should exclude BM's
`-1` "not set" convention from `dangling_values`, mirroring the same
sentinel-awareness already used elsewhere in the codebase (e.g.
`_id_priority_mk`, `condition_function_id == -1` checks). This is a
validator-accuracy fix, not an ingestion-behavior change.

### Phase I — apply_answer constraint validation

`apply_answer` gains an optional `constrained_item_values` parameter
(mirroring `next_question_prompt`'s existing one); when supplied, only
options within that set may match. The Step 5 call site
(`ask_api.py:608`) must pass `constrained_opts.get(pending_attr.entity_id)`
— the exact value already computed and available at that point in the turn.

### Phase J — single-select re-validation

Extend the `if vn in filled:` branch in `auto_fill` to re-check the existing
value against the current `constrained_opts` before skipping — same logic
already built for multi-select (§3c), applied symmetrically. When the
existing value is no longer allowed, clear it, add it to `pending`, and
surface it through the **same** `dropped_multi`-style naming mechanism
(Phase D) so the cascade notice explains "Carrier was reset — no longer
valid after deleting LTE" rather than silently changing state.

**Re-fill after cascade uses Phase N's rule, not the old D2-only rule.**
Per §3g: when `_handle_cascade`/`find_cascade_dependents` clears a
dependent and re-runs `evaluate_rules_loop`, the re-fill must use the same
widened eligibility (governed OR `required=False`, excluding decision-keys)
so a changed attribute's dependents are re-populated exactly as
aggressively as they were on first fill — not a stricter re-fill after a
looser initial fill. `auto_fill`/`evaluate_rules_loop` already take a
single `governed_ids` set computed by `governed_target_ids()`; Phase N
changes what that function returns, so this falls out automatically once
N is implemented — no separate change needed in the cascade path itself.

### Phase K — verbose summary noise filter, widened to define "important"

Two changes, per §3e (exclusion) and the new client spec (§3g, inclusion
criterion):
1. **Exclusion (unchanged from earlier):** underscore-prefix and
   integration-prefix (`CRM_*`-style, derived generically) check on
   `render_filled_summary`'s item filter.
2. **Inclusion/highlighting (new):** the spec defines "important" as
   attrs decided by recommendation, constraint, or hiding rules —
   i.e. exactly `governed_target_ids()`'s output (already computed every
   turn for Phase N). `render_filled_summary` should visually distinguish
   governed decisions (the ones a rule actually reasoned about) from
   attrs that were auto-filled purely because Phase N's `required=False`
   path picked *something* — e.g. two groups: "Key decisions" (governed)
   vs. a terse count for the rest ("+24 other fields auto-configured"),
   rather than one flat list where a rule-driven Region choice and an
   arbitrarily-picked cosmetic toggle look equally significant.

### Phase L — live audit (COMPLETE)

All 10 queries run verbatim against workspace 13 (46,498 entities / 49,165
edges). Results folded into §2c, §2d, §3c, §3d, §3e above. Summary:

| Query | Result | Verdict |
|---|---|---|
| Q1 (missing defaults) | Both attrs have `default_value = None` in CPQ's own data | Confirmed no-default; asking is correct unless rule-governed (§3a) |
| Q2 (surveillance dup) | Both attrs exist, active, distinct | Confirmed real duplication exists in the catalog |
| Q3 (carrier/LTE attrs) | 3 attrs found, correct structure | Extraction working |
| Q4 (LTE-NO-SERVICE menu item) | Found, order 6 of 6 | §2c REFUTED — extraction working |
| Q5 (validationOrg options) | US8/MY8/DE8 found | Extraction working |
| Q6 (LTE-delete rule input, by name) | 0 rows | Query's own search strategy fails on UUID names (§2a) — not a missing-edge bug |
| Q7 (carrier rule action, by name) | 0 rows | Same as Q6 |
| Q8 (surveillance hiding rule, by name) | 0 rows | Traced by id instead: genuinely 0 — confirmed source-data gap (§3d) |
| Q9 (clean summary filter) | Returns `CRM_*` fields at top | Filter as specified is insufficient (§3e widened) |
| Q10 (sanity split) | 121 hidden / 306 user-facing / 427 total | Useful baseline; "user-facing" bucket still needs the §3e refinement to be truly clean |

**Note on method — independently re-verified, not just inferred:** re-ran
queries 6–8 exactly as given (0 rows each, confirmed) plus two diagnostics:
(1) the bare relationship pattern with no `WHERE` clause —
`(Rule)-[:REL]->(RuleInput)` and `(Rule)-[:REL]->(RuleAction)` — returns
real rows immediately, proving the graph structure itself is intact; (2) a
5-row sample of `i.name`/`act.name` for real rows is 100% UUID strings, zero
exceptions. Queries 6–8 rely on name-substring search, which cannot work
against UUID-named nodes (§2a) — proven at the pattern level, not inferred
from one traced example. Re-tracing by attribute id (matching how the live
engine actually resolves rules) is what actually answered §3c/§3d — this is
now the recommended pattern for any future
audit of this rule network, and is captured as S20b in the test plan.

### Phase M — surveillance/carrier mutex decision (HITL — SKIPPED for now, 2026-07-10)

§3c-ii and §3d both trace to the same root shape: two attrs that *should*
be mutually exclusive (or state-linked) have no rule connecting them in
BM's own source catalog. This is not an ETL bug and Phase G cannot fix it —
there is no missing edge, no relationship exists to detect.

⏸ **APPROVAL NEEDED:** choose one before any code is written for this class of issue.
  **Option (i):** report both as BM catalog data-quality gaps to the source
  system owner; no Aryx code change. Fastest, correct if these are meant to
  be fixed at the source.
  **Option (ii):** build a generic same-concept-attr detector (e.g. two attrs
  whose `variable_name` stems match after stripping a `select_type`-style
  suffix, or whose `display_label`s are near-duplicates) and treat detected
  pairs as an Aryx-side mutex safety net, independent of source rules.
  Recommending: **(i) first, (ii) only if the catalog owner confirms these
  gaps are structural across many products**, not just APX Next — building
  (ii) now risks solving a two-instance problem with a permanent heuristic
  that could misfire on legitimately-unrelated attrs elsewhere.
  Risk: if (ii) is skipped, these two specific bugs (surveillance double-
  charge, LTE/Carrier mismatch) remain live until the source catalog is
  fixed — which is outside Aryx's control and timeline.
  → Say "go" to proceed with (i) only, "modify" to scope (ii) instead or
  in addition, or "skip" to leave this open for now.

**Decision: SKIPPED for now (user, 2026-07-10).** Neither option (i) nor
(ii) is being actioned yet. The surveillance double-charge and LTE/Carrier
mismatch bugs remain live and unfixed — this is a known, accepted gap, not
an oversight. Revisit by re-reading this section and choosing (i), (ii), or
(i)+(ii) whenever ready; no code depends on this decision (Phases G–N are
fully independent of it, confirmed by S21's explicit skip rather than a
half-built heuristic).

### Phase N — widened auto-fill eligibility (§3g, APPROVED)

`governed_target_ids()` (`engine.py`) currently returns only entity ids
targeted by a loaded `HidingRule`/`RecommendationRule`/`ConstraintRule`.
Extend it to a two-part eligibility set:

```
eligible = governed_ids ∪ {
    a.entity_id for a in attrs
    if not a.required
    and not any(dk in a.variable_name.lower().replace("_","") for dk in _DECISION_REQUIRED_KEYS)
}
```

`auto_fill`'s existing governed-branch logic (default-or-first,
select_type-aware — single/boolean pick first-by-order, multi picks the
allowed set or stays pending per §3 of `CPQ_CASCADE_CONVERSATION_PLAN.md`)
is **reused as-is** for attrs newly admitted via the `required=False` path
— no new fill logic, only a wider `governed_ids` input. `filled_source`
must record which path admitted the value (`"rule"` vs a new `"optional"`
tag) so `render_filled_summary` (Phase K) and any future audit can tell
"a rule decided this" apart from "this was optional and got a value."

**This changes `CPQ_CASCADE_CONVERSATION_PLAN.md`'s D2 decision** — that
doc should get a short amendment pointing here rather than silently going
stale.

---

## 5. Test additions (zero hardcoding, per project discipline)

All new scenarios derive expectations from whichever export
`ARYX_CPQ_SAMPLE` resolves to (same pattern as `cpq_fixtures.py`) —
`APX_Next_config.xml` becomes the natural default given its richer rule
coverage, but no test may hardcode a value specific to it.

| # | Scenario | Ground truth derivation | Asserts |
|---|---|---|---|
| S15 | FK compound-column detection (Phase G regression guard) | For every `{word1}_{word2}_id`-shaped column in ground truth whose `{word1}_{word2}` prefix matches a real dataset's de-camelCased tag, check `_detect_fk_links`'s output | Every such column resolves to an edge spec; regression guard against the exact class of miss found in §2b |
| S16 | Dangling-FK sentinel exclusion (Phase H) | Any column in ground truth with value `"-1"` | `-1` never appears in `dangling_values`; a genuinely broken (non-`-1`) reference still does |
| S17 | `apply_answer` respects active constraints (Phase I) | Pick a real constrained attr/value pair from ground truth's constraint rules | An answer matching an option **outside** the current allowed set is rejected, not silently accepted |
| S18 | Single-select re-validation on cascade (Phase J) | Pick a real hiding/constraint rule pair where filling attr A invalidates an already-filled attr B (single-select) | B's stale value is cleared and named in the cascade notice, not silently retained |
| S19 | Verbose summary excludes underscore-prefixed attrs (Phase K) | Any config attr with an underscore-prefixed `variable_name` | Never appears in `render_filled_summary`'s output, regardless of fill source |
| S20a | Live audit parity (Phase L — **done manually this session**, formalize as regression) | Run the 10 Cypher queries against any live-ingested workspace | Each query's *purpose* holds — Q4/Q5 menu extraction non-empty, Q9/Q10 counts self-consistent (`hidden + user_facing == total`) |
| S20b | Rule-chain trace-by-id, not by name (regression guard for the Q6/Q7/Q8 method gap found this session) | Pick any real attr referenced by ≥1 rule_input's `attribute_id`; trace forward to that rule's actions by `rule_id` | Chain resolves via id-based lookup even when the rule/action `name` field is a UUID — proves the "search by name" trap from §2a/L doesn't silently produce false "no rule found" negatives elsewhere |
| S21 | Fully-ungoverned duplicate-concept attr detector (data-health check, not a fix) | For every pair of config attrs whose `variable_name` differs only by a pluralization/select_type-style suffix, check whether **either** has zero rule_input AND zero rule_action references | Surfaces the exact §3d pattern (one governed, one fully orphaned) as a reportable list — feeds Phase M's decision with real counts, doesn't itself decide (i) vs (ii) |
| S22 | Verbose filter excludes CRM/system-prefixed attrs (Phase K, widened per §3e) | Any config attr whose `variable_name` matches the same prefix pattern(s) found live in Q9 (derived from data, not a hardcoded list of the exact names seen) | Never appears in `render_filled_summary`'s output |
| S23 | **≤2–3-prompt acceptance test (Phase N, §3g)** — the client's own success criterion | Drive a full conversation from a cold start (`session_data={}`) with product+country given together in message 1; count *user-answered* turns (a turn where a real answer was locked, not a system prompt) until `status` reaches `awaiting_approval` | Total user turns ≤ 3, matching the target; assert this on whatever export is configured — if a richer/different catalog needs more than 3 genuinely-required decisions, the test reports the real count and the *reason* (via `filled_source`), it does not force a false pass |
| S24 | Widened eligibility respects `required` and decision-keys (Phase N regression guard) | Pick a real `required=True` attr and a real decision-key attr (country/region-pattern) with no governing rule, both ungoverned | Neither gets auto-filled via the new `required=False` path — only genuinely-optional, non-decision-key attrs do; regression guard against Phase N over-widening into Issue-6 territory |
| S25 | `filled_source` distinguishes rule-driven from optional-auto-filled (Phase N/K) | Any attr admitted via the new `required=False` path vs. any admitted via existing rule-governance | Sources differ (`"optional"` vs `"rule"`/`"default"`/`"auto"`); `render_filled_summary`'s "Key decisions" grouping (Phase K) only includes the rule-driven set |
| S26 | Cascade re-fill uses Phase N's widened rule symmetrically (Phase J note) | Change a filled attr that invalidates a dependent admitted via the `required=False` path on first fill | The re-filled value after cascade comes from the same widened eligibility, not a stricter fallback — dependent doesn't become newly "pending" just because it's being re-filled instead of first-filled |

S15–S19 and S20b–S26 can be written and run against `APX_Next_config.xml`'s
ground truth via the existing `FakeCpqRdb`/`FakeReader` pattern — **no
ingestion dependency**, confirmed this session (the id-based trace that
answered §3c/§3d used exactly this kind of direct graph query, not
anything ingestion-specific). S23 specifically was already manually proven
live this session (the exact "product+country in one message → 29 pending
→ 2 after Phase N" trace above) — writing it as an automated test using
the same driver pattern as `test_s6_s7_conversation_payload_and_no_eager_output`
formalizes what was already demonstrated, it does not need re-discovery.
S20a is the one manual/live-only piece; formalizing it as an automated
regression is optional future work, not required before Phases G–N land.

**Update — S15-S26 written and run** (`tests/test_cpq_e2e.py`, against a
new `apx_truth`/`apx_fake_rdb` fixture pair scoped to `APX_Next_config.xml`
specifically, alongside the existing `ARYX_CPQ_SAMPLE`-driven fixtures S1-
S14 already use). Result: **22 passed, 2 skipped, 2 failed** (full suite,
`PYTHONPATH=src python -m pytest tests/test_cpq_e2e.py`):
- The 2 failures (`test_s1`, `test_s15`) are the SAME pre-existing,
  unrelated `ImportError: cannot import name 'UTC' from 'datetime'` —
  `source_catalog.py` uses Python 3.11+'s `datetime.UTC`, this dev
  sandbox's ambient interpreter is 3.10, the Dockerfile pins **3.13**. Not
  a regression from this work; S15 is written correctly and will run in
  the real target environment.
- The 2 skips are legitimate data-driven skips (S12b: SL3500e sample
  doesn't surface 2+ pending attrs in one turn; S21: intentionally not
  built, see below) — not failures.
- **S23 passed outright** — no skip fired, meaning the ≤3-user-turn
  assertion held for real on `APX_Next_config.xml` via `FakeCpqRdb`/
  `FakeReader`, confirming the live "29 pending → ~2" trace in an
  automated, repeatable form.
- **S21 was NOT implemented as a working detector** — deliberately, since
  Phase M (the mutex-heuristic decision it would feed) is still an open
  HITL gate. It's written as an explicit `pytest.skip` documenting why,
  not a placeholder that silently passes.

---

## 6. Risks

- **Phase G's generalized matching could over-match** (e.g. a coincidental
  compound-word overlap that isn't a real FK) — mitigate with the same
  cardinality/constant-value guards already used elsewhere in
  `_detect_fk_links` (`_col_is_varying`), not a new allowlist.
- **Phase J's re-validation could thrash** if two rules disagree in a cycle
  (A invalidates B, B's clearing re-triggers a rule that invalidates A) —
  bounded by the existing `_MAX_LOOPS = 8` cap in `evaluate_rules_loop`;
  confirm this is sufficient once tested against APX Next's real 688 rules,
  not just SL3500e's much smaller set.
- **§3d and §3c-ii are confirmed not fixable by Phase G** — the audit
  proved the underlying rule never existed in BM's catalog for these two
  cases. Phase M's HITL gate must not be skipped in favor of jumping
  straight to building option (ii)'s heuristic on the strength of only two
  observed instances.
- **S21's "orphaned duplicate" scan could produce false positives** on
  attrs that are legitimately independent despite similar names — treat
  its output as a candidate list for Phase M's decision, never as an
  auto-fix trigger.

---

## 7. Out of scope

- Building the name-similarity "these attrs look like duplicates" heuristic
  (§3d/§3c-ii, Phase M option ii) — Phase L is done and confirmed the
  simpler explanation (no rule exists); building this is a real scope
  decision gated on Phase M's HITL, not started by default.
- Synthetic display-name generation for unnamed rule actions (§2a) —
  cosmetic, no functional impact, not blocking.
- Fixing the source BM catalog itself (adding the missing surveillance
  hiding rule or the missing carrier/LTE constraint) — outside Aryx's
  codebase entirely; Phase M option (i) is the mechanism for raising this
  with the catalog owner, not a code change here.
