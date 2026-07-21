# CPQ Open Issues — Detailed Problem Statements (as of `feat/cpq-multi-product-session-snapshot` @ `5e50e07`)

Each item below has four parts: **Problem Statement** (what's observed),
**Why It's Occurring** (the mechanism), **Where in the Code** (exact
files/lines), **Where in the Flow** (which conversation step triggers
it). Items are numbered by current priority, not by discovery order.

**Fixed since the last pass** (see `CPQ_SESSION_2_MASTER_ISSUES_AND_FIXES.md`
for full history/commits): items 1–5, 9 there are shipped. The reordered-
phrase change-request gap (previously item 1 here) is now also fixed
(`5e50e07`) and the multi-product session-snapshot plan is implemented
(`8ec531c`). **All 5 items below are now implemented and tested**
(uncommitted in the working tree as of this pass) — see the "Fix
implemented" note at the end of each item. Item 5 was built as Approach B
(ingestion-time graph enrichment) specifically, per explicit direction —
see `CPQ_BML_ARRAY_ITERATION_TIER_PLAN.md`'s own "Status" section for what
that does and doesn't cover (the runtime-consumption side, Approach A,
remains a separate follow-up).

---

## 1. Product-switch confirmation swallows a NEW switch mention as a flat decline

**Problem Statement:** When a switch-confirmation prompt is pending
(e.g. "Switch to pCRBusinessLightDevices_bom and discard the current
configuration? (yes/no)"), a reply that doesn't affirm the CURRENTLY
pending product is unconditionally treated as "no, stay" — even when
that reply itself names a different, real, ingested product. Confirmed
live: after DM4400 triggered a pending switch prompt, replying "Quote
APX Next Enhanced radios for a US customer." (itself a clear switch
request to a third product) got swallowed as "OK — continuing with
videoSolutions_BOM" instead of being recognized as a switch to APX NEXT.

**Why It's Occurring:** The `confirm_switch` gate computes a single
boolean `affirmative` (does the reply start with yes/switch/confirm, or
exactly match the pending product's own name) and branches on it with a
plain if/else. The `else` (decline) branch clears `pending_switch_product`
and returns immediately — it never re-examines the reply text for a
DIFFERENT switch signal. This is structurally identical to the
`suggest_switch` gate a few lines up, which DOES fall through to normal
switch detection on a non-yes/no reply (its own comment says so
explicitly) — `confirm_switch`'s decline branch was never given the same
fallthrough.

**Where in the Code:** [`ask_api.py:948-956`](../src/aryx/api/ask_api.py)
— the `if _sreply.startswith(("n", "no")):` decline branch inside the
`elif session.pending_anchor == "confirm_switch":` block
([`ask_api.py:938`](../src/aryx/api/ask_api.py)). Compare against the
`suggest_switch` gate's own decline handling just above it
([`ask_api.py:946-947`](../src/aryx/api/ask_api.py), which clears state
and lets execution fall through to the normal switch-detection code
later in `_run_cpq_turn`, rather than returning early).

**Where in the Flow:** Turn N+1 after a switch has already been offered
(turn N's response set `pending_anchor = "confirm_switch"` and
`pending_switch_product`). Specifically the reply-handling branch at the
very TOP of `_run_cpq_turn`, before Step 1 (product anchoring) even runs
— so a genuine new switch mention in that reply never reaches the normal
`detect_product_mention` call that would otherwise catch it.

**Proposed fix (scoped, not yet implemented):** Before declining, run
`detect_product_mention`/the alias-map check (same helper used at
[`ask_api.py:1121`](../src/aryx/api/ask_api.py) and
[`ask_api.py:1138`](../src/aryx/api/ask_api.py)) against the reply text.
If it names a real ingested product different from both
`session.product_name` and the currently-pending
`session.pending_switch_product`, replace `pending_switch_product`/
`pending_switch_question` with the new candidate and re-prompt confirm
— never revert to the old product on a message that was actually asking
for something else.

**Fix implemented:** exactly the proposed approach, in the decline branch
at `ask_api.py`'s `confirm_switch` gate. Tests:
`test_decline_reply_naming_a_different_product_reoffers_switch_instead`,
`test_decline_reply_with_no_new_product_still_declines_normally`
(`tests/test_cpq_product_switch.py`).

---

## 2. Duplicate attribute labels — display AND query-resolution both affected

**Problem Statement:** Multiple, functionally distinct attributes across
catalogs share an identical display label in the native XML. Confirmed
recurring, not SVX-specific:
- SVX: `mountType_viSoln` (single-select clip/lanyard mechanism) and
  `mountingTypeArray_viSoln` (multi-select mount hardware array) both
  literally named **"Mounting Type"** — reproduced in 2 separate live
  transcripts, most recently with `mountType_viSoln` = "Swivel Clip and
  Adjustable Lanyard" alongside `mountingTypeArray_viSoln` = "Shirt
  Magnetic Mount, Jacket Magnetic Mount" both rendered as "Mounting Type"
  rows.
- APX NEXT: a confirmed 3-way collision on **"Service Type"**
  (`serviceType_astro`, `serviceTypeRSM_astro`,
  `serviceTypeAdditionalDMSCoverage_astro`), plus 2-way collisions on
  "Duration" and 'Is this a "SPARE radio"'.

**Why It's Occurring:** This is genuine BigMachines source-data reuse —
the native `<name>` field for these attributes is identical across
functionally different attrs (confirmed by reading the raw XML directly,
not an ingestion artifact). Every renderer that shows a human-facing
label keys purely off `display_label`, with no tiebreaker for a
collision. Separately, `detect_attr_query`'s own tiebreak for an
OPTIONS-query ("what are the options for X") — "the longest/most
specific match wins" — is a no-op when the colliding labels are
literally the same string and length, so it silently resolves to
whichever attr happens to be first in list order, never asking. Checked
the native BigMachines editor UI and `ConfigAttr`'s own fields directly:
there is no rep-visible field (variable_name and admin metadata are
backend-only) a customer-facing disambiguation could fall back to.

**Where in the Code:**
- Display path: `CpqEngine._filled_summary_triples()`
  ([`engine.py:4719`](../src/aryx/cpq/engine.py)) — the single shared
  source `beautify_text()`/`beautify_rows()`/`render_filled_summary()`/
  `categorized_summary_groups()` all build on, keyed purely by
  `display_label`.
- Query path: `CpqEngine.detect_attr_query()`
  ([`engine.py:4208`](../src/aryx/cpq/engine.py)), specifically the
  `label_matches` fallback tier
  ([`engine.py:4247-4250`](../src/aryx/cpq/engine.py)) whose
  `max(..., key=lambda a: len(a.display_label))` tiebreak degenerates to
  "first in list order" on an exact-length tie.

**Where in the Flow:** Display path fires on EVERY turn that renders a
summary (mid-conversation "configuring" nudges, the final "Configuration
complete" summary, and the Beautify button/panel). Query path fires when
a rep asks "what are the options for {label}" or a change request names
only the shared label with no value (`detect_attr_query`/
`detect_change_request`'s label-mention gate).

**Proposed fix (scoped, not yet implemented):** Two parts, both
necessary — (a) in `_filled_summary_triples()`, disambiguate colliding
labels by appending `variable_name` in parentheses; (b) in
`detect_attr_query`, when 2+ attrs tie on label, don't resolve silently
— return/prompt all candidates with their CURRENT VALUES as the
human-readable distinguisher, reusing the same clarify-before-guessing
pattern `suggest_switch` ([`ask_api.py:875`](../src/aryx/api/ask_api.py))
already uses for ambiguous product mentions.

**Fix implemented:** both parts. (a) `_filled_summary_triples()` now
appends `(variable_name)` to any `display_label` shared by 2+ distinct
attrs. (b) new `CpqEngine.detect_label_collision()` runs before
`detect_attr_query` at both call sites in `ask_api.py`; on a genuine label
tie it returns a clarify prompt listing each candidate's variable_name and
current value instead of silently resolving to one. Tests:
`tests/test_cpq_label_collision.py`.

---

## 3. `mountingArrayControl_viSoln`'s value has no connection to the real per-row quantity

**Problem Statement:** Live transcript (SVX, Locking Molle Mount,
quantity answered "7"): `mountingTypeLockingMolleMountQuantity_viSoln`
correctly shows `7` in the payload, but `mountingArrayControl_viSoln
.items[0].value` shows `"5"` — a different, seemingly arbitrary number.

**Why It's Occurring (newly traced this pass):** `mountingArrayControl
_viSoln` is recognized structurally as the array's SIZE/control
attribute (`ConfigAttr.is_array_control`, set from the raw XML's
`additional` metadata — [`engine.py:1877`](../src/aryx/cpq/engine.py))
but **no code anywhere ties its VALUE to the real answered quantity**.
The mechanism that actually captures "the customer said 7" is a
completely separate, purpose-built heuristic —
`resolve_array_grid_links()`/`resolve_pending_grid_quantities()`
([`engine.py:2211-2286`](../src/aryx/cpq/engine.py)) — which asks for
and fills the PER-OPTION quantity attr
(`mountingTypeLockingMolleMountQuantity_viSoln`) directly, and never
touches `mountingArrayControl_viSoln` at all. Left to itself,
`mountingArrayControl_viSoln` just goes through the GENERIC `auto_fill`
path like any other unrelated attr — governed blind-fallback, a
recommendation-rule default, or first-by-order — landing on whatever
value that generic mechanism happens to produce, with zero connection to
the real per-row answer the customer gave through the OTHER mechanism.
The "5 vs 7" mismatch is a symptom of two independent, uncoordinated
fill paths for what a human would assume is one fact.

**Where in the Code:** `auto_fill()`
([`engine.py:3263` signature, governed/blind-fallback branch around
`engine.py:3707-3708`](../src/aryx/cpq/engine.py)) is what fills
`mountingArrayControl_viSoln` (as an ordinary attr, no special-casing) —
disconnected from `resolve_pending_grid_quantities()`
([`engine.py:2255-2286`](../src/aryx/cpq/engine.py)), which fills the
sibling per-option quantity attr from the user's real answer.

**Where in the Flow:** Every turn `auto_fill` runs (i.e. every turn) for
a catalog with this array-control construct — the mismatch is written as
soon as the array-control attr first gets a value, independent of
whether/when the customer answers the per-mount quantity question.

**Not yet fixed — needs a decision:** should `mountingArrayControl
_viSoln` be (a) derived from the per-option quantity/quantities once
known (sum, or the single active row's value), or (b) excluded from the
payload entirely as internal BigMachines scaffolding the native UI never
surfaces directly (recall it's `hidden=1` in the raw XML — same class of
attr as the per-option quantities before their own hidden-attr-visibility
fix landed on dev). Recommend (b) unless a real downstream consumer
(pricing, BOM generation) depends on this specific field's value.

**Fix implemented, then CORRECTED:** option (b) (exclude entirely) shipped
first, but a genuine reference payload obtained afterward (`"mountingArray
Control_viSoln": 6`, a bare int matching its array-set's row count)
confirmed that assumption was wrong — BigMachines DOES expect this attr in
the payload. Corrected to option (a) in spirit: `build_payload()` now
derives it as a bare int equal to the number of selected values in the
catalog's array selector, but ONLY when the link is structurally
unambiguous (exactly one `is_array_control` attr and exactly one
`select_type=="multi"` attr among the loaded attrs) — deriving it by
NAME-matching control↔selector across multiple candidates would be exactly
the guessing `resolve_array_grid_links`'s own docstring already refuses to
do for this catalog family, so any ambiguous case still abstains (same as
the original exclusion). The raw, disconnected `filled` value (still just
whatever `auto_fill` happened to pick) is never shipped either way. Tests:
`test_array_control_attr_derives_row_count_when_link_is_unambiguous`,
`test_array_control_attr_abstains_when_the_link_is_ambiguous`
(`tests/test_cpq_payload_shapes.py`).

**Superseded by the durable fix — the full array-set implementation is now
also shipped**, see [`CPQ_ARRAY_SET_PAYLOAD_PLAN.md`](CPQ_ARRAY_SET_PAYLOAD_PLAN.md)
for the complete design/verification. `mountingArrayControl_viSoln` and
`mountingTypeArray_viSoln`/`mountingTypeArrayqty_viSoln` are now correctly
linked via a REAL ingested `bm_config_attr_set`/`bm_config_attr_set_assoc`
join, not the narrower single-control/single-multi-select heuristic (which
still exists as a fallback for catalogs/attrs with no real array-set link
data). Verified live against the actual ingested SVX catalog (workspace
19) — `build_payload()` now produces byte-for-byte the same shape as the
original reference payload.

**New, separate, NOT YET IMPLEMENTED finding from the same reference
payload — now partially confirmed against Postgres (workspace 19):**
`archeType_viSoln` and `modelSelectionSelectModel_viSoln` appear
double-wrapped — `{"value": {"value":.., "displayValue":..}}` — one extra
nesting level beyond the normal single-select `{"value":..,
"displayValue":..}` shape every other menu attr in this same payload uses.
Queried the raw `bm_config_attr` rows for both directly: both carry
`set_type: "2"` and `auto_lock: "1"` — and a third attr in the same
catalog, `serviceType_viSoln`, shares the EXACT same `set_type=2,
auto_lock=1` signature (vs. e.g. `mountingArrayControl_viSoln`'s
`set_type=1, auto_lock=0`), suggesting this is a real, consistent field
combination, not coincidence. **Still not fully confirmed**: no code today
reads `auto_lock` at all (`ConfigAttr` has no such field, only the
existing numeric `set_type` — note this is `bm_config_attr.set_type`, a
DIFFERENT field from the driver-row `bm_config_attr_set` concept in
`CPQ_ARRAY_SET_PAYLOAD_PLAN.md`, unfortunate naming overlap in the source
data itself), and `serviceType_viSoln`'s own payload shape hasn't actually
been observed double-wrapped in any sample yet — only its metadata
matches. Needs one more real payload sample containing `serviceType_
viSoln` to confirm the mechanism before scoping a fix.

**Contradiction surfaced while scoping:** `build_payload()` (`engine.py:
4737`) ALREADY excludes any `set_type=="2"` attr from the payload entirely
— and its own comment literally names `modelSelectionSelectModel/
archeType/serviceType/dMSDuration_viSoln` as the confirmed real examples
(from an earlier, separately-verified "workspace 14" finding,
`docs/CPQ_PRODUCT_SWITCH_ISSUE.md` Issue 5 — same attrs this finding is
about). But the new reference payload shows `archeType_viSoln`/
`modelSelectionSelectModel_viSoln` PRESENT (double-wrapped), not excluded.
Resolved (by direction, not yet by code): `auto_lock` is the
discriminator. The `set_type==2` exclusion is correct ONLY for `auto_lock
==0` attrs (genuinely transient UI/action-layer attrs, e.g. `_price_book_
var_name`/`mergePackage`/`update` — the original workspace-14 evidence,
none of which carry `auto_lock==1`); a `set_type==2` attr with `auto_lock
==1` is a real, includable value that needs the double-wrap shape
instead of being dropped.

**Fix implemented:**
- `ConfigAttr` (`state.py`): added `auto_lock: bool = False`.
- `engine.py`'s `ConfigAttr` construction (~1908-1923): parse `pg.get(
  "auto_lock")` the same boolean-flag way `is_hidden`/`is_array_control`
  already are.
- `engine.py:4737`'s exclusion check becomes `attr.set_type == "2" and not
  attr.auto_lock` — an `auto_lock==1` attr now falls through to normal
  per-type serialization instead of being dropped.
- After that attr's normal shape is computed (whatever `select_type`
  resolves to — confirmed `"single"`/menu-backed for all 3 known examples,
  `data_type=1`+`menu_type=1` on all of them), wrap it once more:
  `if attr.set_type == "2" and attr.auto_lock and k in out: out[k] =
  {"value": out[k]}` — generic over whatever shape was already built,
  not special-cased to the single-select branch specifically.
- The `filled_multi` loop's own separate `set_type=="2"` check
  (`engine.py:4800`) is UNCHANGED — no confirmed example of a multi-select
  `auto_lock==1` attr exists yet; scope stays narrow to what's evidenced.
- Tests: `test_set_type_2_attr_with_auto_lock_is_included_double_wrapped`
  (archeType_viSoln-shaped fixture: `set_type="2"`, `auto_lock=True`, real
  options → asserts `{"value": {"value":.., "displayValue":..}}`) and
  `test_set_type_2_attr_without_auto_lock_still_excluded` (regression guard
  — the ORIGINAL workspace-14 transient-attr exclusion, `auto_lock=False`
  by default, confirmed completely unaffected) — both in
  `tests/test_cpq_payload_shapes.py`.

---

## 4. Cascade-invalidated non-hidden attribute silently vanishes; flow still claims "Configuration complete"

**Problem Statement:** Picking "Locking Molle Mount" cascades and
correctly invalidates `serviceType_viSoln`'s prior answer (the response
correctly states "Removed TECH SUPPORT AND HARDWARE REPAIR from Service
Type — no longer valid after this change"), but the attribute is never
re-asked and disappears from both the summary and the final payload —
confirmed via the raw XML this attr is NOT hidden (`hidden=0`) and NOT
suppressed by the active Solution Type condition (that rule targets a
different attribute, Service Duration). Despite this, the flow declares
"Configuration complete" and offers submission with a real,
previously-answered decision silently missing.

**Why It's Occurring (newly traced this pass):** The "Removed X from Y —
no longer valid" phrasing is `_handle_cascade`'s `dropped_multi` cascade
note ([`ask_api.py:624-630`](../src/aryx/api/ask_api.py)) — this is a
SEPARATE mechanism from `find_cascade_dependents`'s ordinary dependent-
invalidation, triggered inside `evaluate_rules_loop`
([`ask_api.py:575-581`](../src/aryx/api/ask_api.py)) when a constraint
rule re-narrows an already-filled attr's allowed values after the
cascade. Once cleared, the attr re-enters `auto_fill`
([`ask_api.py:584-590`](../src/aryx/api/ask_api.py)) on the SAME turn —
and if it qualifies for the governed blind-fallback branch (`is_governed
and not is_decision_attr and valid_opts`,
[`engine.py:3707-3708`](../src/aryx/cpq/engine.py)), it gets SILENTLY
auto-filled with a new (first-by-order or default) value rather than
being added to `pending`. Because `session.pending_variables` only ever
reflects `pending`'s contents, and the completeness check
(`if pending:` vs the `else` "Configuration complete" branch,
[`ask_api.py:632-654`](../src/aryx/api/ask_api.py)) trusts that list
completely, a silently-auto-refilled attr is by definition never
flagged as incomplete — whether or not the auto-picked replacement value
is one the customer would actually want is never surfaced to them.

**Where in the Code:**
- Cascade note / dropped-value detection:
  [`ask_api.py:624-630`](../src/aryx/api/ask_api.py) (message text) fed
  by `evaluate_rules_loop`'s constraint re-validation
  ([`engine.py:3465-3478`](../src/aryx/cpq/engine.py), the same
  "cascade may have narrowed this attr's allowed set" logic verified
  earlier this session for the snapshot-restore work).
- Silent re-fill: `auto_fill`'s governed blind-fallback branch
  ([`engine.py:3707-3708`](../src/aryx/cpq/engine.py)).
- False-complete claim: the `if pending: ... else: ... "Configuration
  complete"` branch ([`ask_api.py:632-654`](../src/aryx/api/ask_api.py)).

**Where in the Flow:** STEP 6 (Cascade) — any turn that answers/changes
an attribute whose cascade invalidates a SIBLING attr that (a) is itself
rule-governed (`is_governed=True`) and (b) has more than one remaining
valid option after re-narrowing, so it qualifies for blind fallback
instead of landing in `pending`.

**Not yet fixed — needs a decision:** should a cascade-invalidated,
previously USER-ANSWERED attr (i.e. `filled_source == "user"`) be exempt
from the blind-fallback auto-fill path and forced into `pending` instead
— on the reasoning that a real customer decision, once cascaded away,
deserves to be re-asked rather than silently re-guessed, even when a
generic ungoverned attr in the same situation would be fine to
auto-fill? This mirrors the exact reasoning already applied to
product-identifier attrs (`_PRODUCT_IDENTIFIER_KEYS`, never silently
guessed) — recommend generalizing that same principle to any attr whose
CURRENT value's `filled_source` was `"user"` before the cascade cleared
it.

**Fix implemented:** exactly this — `auto_fill()` now tracks
`user_answered_dropped_ids`, populated when the single-select
re-validation clears a value whose `filled_source` was `"user"`, and the
governed blind-fallback branch excludes any attr in that set (falling
through to `pending` instead). Non-`"user"` drops (default/rule/etc.)
keep the prior blind-fallback behavior unchanged. Tests:
`tests/test_cpq_cascade_user_answered_reask.py`.

---

## 5. Mounting Type array construction has no deterministic BML evaluator tier

**Problem Statement:** `mountingTypeArray_viSoln`'s per-option derived
attributes (boolean flags like `isMountingTypeJacketMagneticMount_viSoln`,
quantity rollups) are populated in the native system by a BML script
using a `range(control_attr)` + `selector[idx]`/`qty[idx]` array-iteration
idiom that `BmlEvaluator` has no deterministic tier for.

**Why It's Occurring:** `bml.py`'s Tier 1 (`_TIER1_BLOCKERS`,
[`bml.py:54-57`](../src/aryx/cpq/bml.py)) explicitly excludes any script
containing `for`/`while` — every array-iteration script is routed
straight past Tier 1 to the slow, non-deterministic LLM Tier 2, which
regularly times out under this environment's LLM throughput (confirmed
live, twice, this session — both a broad and a narrowed rule-count pass
stalled on LLM connectivity). Confirmed via direct XML analysis this
idiom recurs heavily across all 3 available catalog exports (SVX 124
subscript reads, APX NEXT/DM4400 162, SL3500e 74) — a systemic gap, not
one-off.

**Where in the Code:** `BmlEvaluator.allowed_values_for_script()`/
`hide_for_script()`/`condition_holds()`
([`bml.py:607`](../src/aryx/cpq/bml.py) onward) — the tiering logic that
tries Tier 1 then falls to Tier 2 with no tier in between for this idiom.

**Where in the Flow:** Any rule evaluation (hiding/constraint/
recommendation) whose target or condition is one of the per-option
derived attrs — i.e. every turn touching `mountingTypeArray_viSoln` (or
the equivalent APX NEXT/SL3500e array constructs) once enough rows are
filled for these derived rules to matter.

**Full plan:** see
[`CPQ_BML_ARRAY_ITERATION_TIER_PLAN.md`](CPQ_BML_ARRAY_ITERATION_TIER_PLAN.md)
— two approaches scoped (runtime evaluator tier vs. ingestion-time graph
enrichment); the plan itself recommends building the runtime tier first.

**Fix implemented:** Approach B (ingestion-time graph enrichment) was
built directly, per explicit direction, rather than the recommended
runtime-tier-first order. New `parse_array_iteration()`/
`ArrayIterationShape` in `bml.py` structurally recognize the idiom (both
the boolean-flag and quantity-copy variants); new
`_detect_script_data_flow_links()` in `doc_discovery.py` runs that
recognizer once per ingest over every `bm_function.script_text`, and for
each recognized script materializes the fact as 3 derived CSV columns +
matching fk_link specs (`BMFUNCTION_ARRAY_ITERATES`/
`BMFUNCTION_READS_SELECTOR`/`BMFUNCTION_READS_QUANTITY`), reusing the
existing `link_by_attribute` value-equality join — no new pipeline
plumbing. Wired into `ingest_confirmed()` alongside `_detect_fk_links`.
**Not built:** the runtime tier itself (Approach A) — no
`evaluate_array_tier`, no new `bml.py` evaluator wiring, no `engine.py`
call-site threading — so `BmlEvaluator` still falls through to Tier 2 for
these scripts at evaluation time; only already-ingested catalogs re-ingested
after this change gain the new graph edges. Tests:
`tests/test_cpq_bml_array_iteration.py` (8 tests).
