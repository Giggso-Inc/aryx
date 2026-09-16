# CPQ Master Issues & Fixes — Switching, Change-Requests, Mounting-Type Array, Session Memory

Consolidates every issue analyzed/fixed in this continuation session on
`feature/msi_cpq`, workspace 19 (SVX / APX Next Enhanced / SL3500e / DM4400
catalogs), in the same Problem/Fix format as
`CPQ_SESSION_CHANGES_SUMMARY.md`. Two items are full standalone plans
(linked, not duplicated in full) rather than one-line fixes; everything
else is fixed-and-shipped or still open.

---

## 1. Product-identifier seeded from the resolved family name, not the specific product
**Commit:** `a16bef9`

**Problem:** After a confirmed product switch, `productSelectionProduct_all`
still got re-asked on the very next turn even though the switch-trigger
message already proved the identity via `detect_product_mention`.

**Fix:** Seed `productSelectionProduct_all` directly from `session
.product_name` via the same fuzzy option-matcher normal answers use,
mirroring the existing confirmed-country carry-over.

---

## 2. `skip_always_ask` inconsistently respected for product-identifier attrs
**Commits:** `0ea508d`, `b4ea3bf` (Raven review findings, two separate gating points)

**Problem:** `is_decision_attr`'s generic `_PRODUCT_IDENTIFIER_KEYS`
fragment match forced an always-ask regardless of `skip_always_ask`,
unlike the adjacent `productSelectionProduct_all`-specific branch — and
even after fixing that, a SEPARATE pending-queue guard was still
hardcoded to exclude only `productSelectionProduct_all` by exact name,
missing any other product-identifier attr for ungoverned cases.

**Fix:** Generalized both gates to respect `skip_always_ask` the same way
for any `_PRODUCT_IDENTIFIER_KEYS`-matching attr, with regression tests
proving each gap independently (fails without the fix, passes with it).

**Superseded (dev, PR #107):** this broad `_PRODUCT_IDENTIFIER_KEYS`
approach was **reverted** (`107ca98`) — confirmed live it caused Base
Model (APX/SL3500e) to wrongly force always-ask again, since option-count
alone can't separate "genuinely ambiguous" (SVX's Select Model, which
mixes real variants with an unrelated accessory at order=1) from "fine to
auto-fill" (APX's Base Model, same option-count range but no such mixing).
Replaced by a narrower fix scoped ONLY to `"selectmodel"`-fragment attrs
(`5c5a445`), with the equivalent `skip_always_ask` carve-out ported
forward for that narrower scope (`c570bf4`). **Net effect: the underlying
intent of this item is still fixed, just via a safer, more narrowly
scoped mechanism than originally implemented.**

---

## 3. `productSelectionProduct_all` seeding silently failed for multi-product catalogs
**Commit:** `e050171`

**Problem:** Fix #1 above only works when `session.product_name` textually
matches an option — true for single-product catalogs, but
`detect_product_mention` resolves multi-product catalogs (aSTRO25_bom
hosts 325 products, pCRBusinessLightDevices_bom hosts 325) to the FAMILY
name, not the specific product ("APX Next Enhanced", "DM4400") the user
actually said. Confirmed live: Product still got re-asked after switching
to either.

**Fix:** Added `CpqSession.pending_switch_question`, carrying the raw
switch-trigger text through to seed time — tried first (it usually names
the specific product), falling back to `product_name` for the
single-product case that already worked.

---

## 4. Parallel summary-format fixes reconciled after a colleague's PR merge
**Commit:** `24d7c1f` (merge)

**Problem:** `origin/feature/msi_cpq` gained two commits
(`e788c9d`/`e1a6e14`) that independently rewrote `_cpq_summary_text` from
an earlier common ancestor — reintroducing the exact hallucination-prone
placeholder phrase ("plus the usual regional and packaging defaults")
this session's own fix (`0d4ff3d`) had removed, plus a different header
style than what had been approved.

**Fix:** Reconciled by keeping the incoming commit's more robust
code-assembled delimiter mechanism, while restoring the bold `**Category:**`
bullet format and the omit-if-uncertain anti-hallucination rule.

---

## 5. Change-request matching failed for compound labels and free-text quantities
**Commit:** `d79b069`

**Problem:** "Change the jacket magnetic mount quantity to 15" fell
through to "I didn't quite catch that" even though the attr and value
were both clearly stated, because (a) `detect_change_request`'s
label-mention gate required the ENTIRE display label
("mounting type Jacket Magnetic Mount Quantity") as a literal substring —
the generic "mounting type" prefix a user naturally drops — and (b)
free-text (no-options) attrs had NO value-extraction mechanism at all
once matched; `extract_hints()` only knows fixed concepts, never numbers.

**Fix:** Added `_label_mentioned()` (suffix-drop tolerance, up to 2
leading words) and a numeric-extraction branch for the free-text
`has_change_verb` case.

**Known remaining gap (not yet fixed):** only handles a dropped PREFIX,
not a REORDERED phrase — "change the quantity of jacket magnetic mount"
(quantity stated before the mount name, reversed from the label's own
word order) still fails the same way, since the matcher only tries
suffixes of the label in its original order. Confirmed recurring in the
latest live transcript. Lower priority than #6 below; same fix family
(the recognizer would need word-SET containment instead of
suffix-substring matching — deferred pending a decision on false-positive
risk, since bag-of-words matching is looser than every other matcher in
this file). **Still open as of dev `c570bf4`** — checked `_label_mention_span`
directly, it reuses the same prefix-drop-only logic, no reordering support added.

**Follow-up fix landed (dev, `c570bf4`):** a SEPARATE bug in this same
numeric-extraction code — when a message names two SIBLING quantity
attrs in one sentence (SVX's per-mount quantity attrs are all named
"mounting type {Mount Name} Quantity"), both attrs' searches
independently grabbed the SAME first "to N" number in the message,
whichever attr `attrs` iteration reached first winning regardless of
which number was actually meant for it. Fixed via `_label_mention_span()`
scoping each attr's numeric search to the text between that attr's own
label mention and the next sibling's.

---

## 6. Product switch confirmation swallows a NEW switch mention as a flat decline
**Status: found, not yet fixed**

**Problem:** [ask_api.py:900-943](../src/aryx/api/ask_api.py) — when
`pending_anchor == "confirm_switch"` and the reply doesn't affirm the
*currently* pending product, the code unconditionally treats it as
"no, stay" and clears the pending switch. Confirmed live: after DM4400
triggered a pending switch-to-`pCRBusinessLightDevices_bom` prompt, the
reply "Quote APX Next Enhanced radios for a US customer." — itself a
clear, different switch request — got swallowed as "OK — continuing with
videoSolutions_BOM" instead of being recognized as a switch to APX NEXT.

**Proposed fix:** before declining, re-run the same
`detect_product_mention`/alias-map check already used elsewhere in this
file against the reply text. If it names a real ingested product
different from both the current and the pending one, replace
`pending_switch_product`/`pending_switch_question` with the new candidate
and re-prompt confirm, instead of declining and reverting to the old
product. Not yet implemented — awaiting approval.

---

## 7. Mounting Type array construction & BML array-iteration evaluator gap
**Status: investigated + full standalone plan written, not yet implemented**

**Problem:** `mountingTypeArray_viSoln` is a real BigMachines
Configurable Attribute Set (size attr `mountingArrayControl_viSoln` +
member columns `mountingTypeArray_viSoln`/`mountingTypeArrayqty_viSoln`),
and per-option derived attrs (`isMountingType{Option}_viSoln`,
`mountingType{Option}Quantity_viSoln`, `hidden=1` natively) are populated
by a native BML script using a `range(control_attr)` +
`selector[idx]`/`qty[idx]` array-iteration idiom that `BmlEvaluator` has
no tier for — `_TIER1_BLOCKERS` explicitly excludes any script containing
`for`, so it always falls to the LLM (Tier 2) or times out. Confirmed
this exact idiom recurs heavily across all 3 available catalog exports
(SVX 124 subscript reads, APX NEXT/DM4400 162, SL3500e 74 — loop-variable
name differs per script: `idx`/`cnt`/`each`/`cntEach`/`i`/`k`), so it's a
systemic gap, not one-off.

**Fix (full plan):** see
[`CPQ_BML_ARRAY_ITERATION_TIER_PLAN.md`](CPQ_BML_ARRAY_ITERATION_TIER_PLAN.md)
— two approaches scoped: **Approach A** (a new runtime `bml.py` tier that
structurally recognizes and evaluates this idiom, replacing the LLM
round-trip for derived values like the boolean flags) and **Approach B**
(a one-time static-analysis pass at ingestion writing the same fact as
permanent graph edges). Recommendation: build A first (immediate value,
zero re-ingestion, and B's design deliberately reuses A's recognizer).
Also documents why the graph doesn't already capture this: ingestion's
FK-discovery is generic/structural (column-name driven), but BML
`script_text` is stored as an opaque blob, never parsed into graph facts.

**Scope note:** this does NOT eliminate asking the user for each mount
option's quantity — that's a real business decision with no other source.
It only makes DERIVED rules (like the boolean flags) deterministic
instead of an LLM call.

**Related, already-fixed side issue (dev, `5c5a445`):** a SEPARATE bug in
this same neighborhood — `mountingTypeLockingMolleMountQuantity_viSoln`
(and its siblings) are `hidden=1` in the raw XML, and the summary's
own exclusion filter was dropping them entirely even when the customer
directly answered them in THIS chat interface (which has no native grid
widget fallback), so a real "15" the customer gave was silently missing
from every summary despite being correctly captured in the payload.
Fixed by threading `filled_source` through so a hidden attr with
`source="user"` is no longer excluded. **This is a display-visibility
fix only — it does NOT touch the BML array-iteration evaluator gap
this item is actually about, and does NOT explain item 10's separate
`mountingArrayControl_viSoln` value-mismatch finding below** (different
attr, different mechanism).

---

## 8. No persisted session memory across product switches (the "session DB" question)
**Status: full standalone plan written, not yet implemented**

**Problem:** Switching products mid-session (A → B → C → back to A)
discards each product's in-progress answers by design
(`_complete_product_switch` resets `filled`/`display_filled`/etc. to
empty on every switch) — confirmed intentional scope cut, not a
technical wall. There is also no DB-backed session store at all today:
`session_data` is a plain client-held JSON blob (`CpqSession.to_dict()`/
`from_dict()`), round-tripped through the client on every `/ask` call;
the only DB write (`_persist_cpq_history`) logs Q&A text for the history
UI, never the actual CPQ config state.

**Fix (full plan):** see
[`CPQ_MULTI_PRODUCT_SESSION_SNAPSHOT_PLAN.md`](CPQ_MULTI_PRODUCT_SESSION_SNAPSHOT_PLAN.md)
— add `CpqSession.product_snapshots: dict[str, dict]`, keyed by product
family, snapshotted on switch-away and restored (via `auto_fill`'s
existing `already_filled` re-validation path — no new validation
machinery) on switch-back, capped at 5 entries. Country carry-over
precedence against the existing switch-confirmation logic traced and
confirmed conflict-free. Still a client-held JSON blob — no new DB table
required.

---

## 9. Duplicate attribute labels in Beautify/review output — confirmed cross-catalog, not SVX-only
**Status: scoped, not yet implemented**

**Problem:** The Beautify table/text view (and, by extension,
`render_filled_summary`'s prose fallback, since both share the same source)
shows multiple rows under the SAME label with different values — e.g. SVX's
two "Mounting Type" rows ("Swivel Clip and Adjustable Lanyard" and "Jacket
Magnetic Mount"). **Confirmed this is not SVX-specific or a missing-rule
bug**: checked a full APX NEXT quote payload against the raw XML and found
3 separate collision groups in a SINGLE quote:

| Shared label | Distinct attrs, distinct values |
|---|---|
| "Service Type" | `serviceType_astro`→Advantage, `serviceTypeRSM_astro`→1 Year Standard Warranty, `serviceTypeAdditionalDMSCoverage_astro`→Premier (a THREE-way collision) |
| "Duration" | `serviceDuration_astro`→10 Years, `solutionTypeDuration_astro`→5 Years |
| 'Is this a "SPARE radio"' | `isThisASPARERadioBatt_astro`→Yes, `isThisASPARERadioAntenna_astro`→Yes |

Root cause traced to the catalogs' own source data (not an ingestion or
matching bug — already verified the NL matcher correctly disambiguates
same-label attrs by option vocabulary, see the earlier `mountType_viSoln`
vs `mountingTypeArray_viSoln` analysis): BigMachines' native XML
genuinely gives multiple, functionally distinct attributes the identical
short display label. All of them flow through
`CpqEngine._filled_summary_triples()`
([engine.py:4719](../src/aryx/cpq/engine.py)) — the shared source
`beautify_text()`/`beautify_rows()`/`render_filled_summary()`/
`categorized_summary_groups()` all build on — which keys purely off
`display_label`, so any group of attrs sharing a label produces
identical-looking rows with no way to tell them apart.

**Scoped fix (display path):** in `_filled_summary_triples()`, after
building the filtered `(var, label, value)` list, detect labels that
occur more than once and disambiguate ONLY those duplicates by appending
the `variable_name` in parentheses — e.g. `"Mounting Type
(mountType_viSoln)"` vs `"Mounting Type
(mountingTypeArray_viSoln)"`. Deterministic (variable_name is always
unique, so this never needs a semantic guess at what distinguishes them),
generic across any catalog (no per-catalog literal), and zero-risk to
every attr that ISN'T part of a collision (single-occurrence labels are
untouched). Small, localized change — one method, no interface change,
since it operates on the triples list before `filled_summary_pairs()`/
`categorized_summary_groups()` consume it downstream.

**Widened problem — the QUERY path has the same collision, and
variable-name disambiguation doesn't help a real rep there.** A rep
asking mid-conversation "what are the options for service type" or
"change the service type" hits `detect_attr_query()`
([engine.py:4208](../src/aryx/cpq/engine.py)) /
`detect_change_request()`'s label-mention gate, both of which also key
off `display_label`. `detect_attr_query`'s own tie-break — "the
LONGEST/most specific match wins" — is a no-op when every colliding
label is the identical string (all 3 "Service Type" attrs), so it
silently resolves to whichever one happens to be first in list order,
not necessarily the one meant. Checked whether the native BigMachines UI
gives a rep some OTHER visible signal to disambiguate by (a layout
section/page name, a grouping label) — traced through the two Menu/Text
Attribute Editor screenshots and `ConfigAttr`'s own fields
([state.py:125](../src/aryx/cpq/state.py)): **no such field exists.**
Every editor field shown (Category, Data Type, Array Type, Display
Order) is backend-only metadata never surfaced to an actual quoting rep,
and `ConfigAttr` captures no layout/section grouping at all. Asking a
rep to know or supply the `variable_name` (the only currently-unambiguous
identifier) is not realistic — they never see it.

**Fix (query path) — reuse the existing clarify-before-guessing
pattern:** this codebase already has the right shape for this in the
product-switch flow — `suggest_switch` ([ask_api.py:864](../src/aryx/api/ask_api.py))
lists every real candidate and asks "Which one did you mean?" instead of
picking one when detection is ambiguous. Extend `detect_attr_query`
(and the `detect_change_request` label-mention gate) the same way: when
2+ attrs share a label with no other signal to break the tie, don't
resolve silently — return all candidates, and prompt using each one's
**current value** as the human-readable distinguisher (visible in the
review screen already, unlike variable_name or admin metadata), e.g.:

> "Service Type" is ambiguous — which one? **Advantage** (main service),
> **1 Year Standard Warranty** (RSM warranty), or **Premier** (DMS
> coverage)?

This closes the gap for the whole conversational flow, not just the
static Beautify/summary display — the display fix (variable_name suffix)
and the query fix (clarify-with-values prompt) are companion pieces of
the same underlying issue, not alternatives.

**Test plan:**
1. Display path: a regression test constructing two `ConfigAttr`s with
   the same `display_label` and different `variable_name`s, asserting
   `filled_summary_pairs()` returns two visibly distinct labels (both
   suffixed) while a third, non-colliding label in the same call stays
   unsuffixed.
2. Query path: `detect_attr_query`/`detect_change_request` given 3
   filled attrs sharing one label and no variable_name/value hint in the
   question — assert a clarify-style result (all 3 candidates + their
   current values) is returned/raised instead of an arbitrary single
   pick; a control case with a value-specific question ("...to Premier")
   still resolves directly, unaffected.

---

## 10. `mountingArrayControl_viSoln` value doesn't match the actual per-row quantity entered
**Status: found, not yet investigated at the code level**

**Problem:** Live transcript (SVX, Locking Molle Mount, quantity "7"):
the payload correctly shows `mountingTypeLockingMolleMountQuantity_viSoln:
7`, but `mountingArrayControl_viSoln.items[0].value` is `"5"` — the
array Configurable Attribute Set's own size/control attribute (see item
7's analysis of `bm_config_attr_set` / `size_attr_id`) doesn't reflect
the row's real quantity. These two values represent the same underlying
fact (how many Locking Molle Mounts) and must agree.

**Not yet root-caused:** haven't traced which code path writes
`mountingArrayControl_viSoln`'s value — worth checking whether it's
being set from a stale/earlier turn's quantity (e.g. the FIRST previously
attempted mount type before the cascade-driven Mounting Type re-ask), or
from an unrelated recommendation/default rule that doesn't actually track
the live row. Needs a live-session repro (Docker) to inspect
`session.filled["mountingArrayControl_viSoln"]` across the turn where
the quantity "7" was answered, to see exactly when/how "5" got written.

---

## 11. Cascade-invalidated non-hidden attribute silently vanishes, but the flow still claims "Configuration complete"
**Status: found, not yet investigated at the code level**

**Problem:** Same transcript: picking "Locking Molle Mount" triggers a
cascade removing `serviceType_viSoln`'s prior answer ("Removed TECH
SUPPORT AND HARDWARE REPAIR from Service Type — no longer valid after
this change" — `find_cascade_dependents`/`_handle_cascade`'s
invalidation mechanism, confirmed working as designed for THIS part).
But `serviceType_viSoln` is never re-asked afterward, and is missing
from both the final categorized summary and the submitted JSON payload
— confirmed via the raw XML that this attr is **not** hidden
(`hidden=0`) and **not** suppressed by the active Solution Type=CapEx
Purchase condition (the rule that fires there,
`hideServiceDurationIfSolutionTypeIsCapExPurchaseBOM`, targets *Service
Duration*, a different attr — not Service Type). Despite this, the flow
says "Configuration complete" and offers to submit, even though a
real, visible, previously-answered decision was silently dropped.

**Not yet root-caused:** this looks like a gap in how invalidated
dependents get folded back into `pending_variables` after a cascade —
`_handle_cascade` strips the dependent's value from `filled` (correct,
since it's now stale) but the completeness check that decides
"Configuration complete" vs. "N attribute(s) still need input" may not
be re-running against the FULL required/decision-attr set after a
cascade the same way it does on a normal turn. Needs a live-session
repro to inspect `session.pending_variables` right after this specific
cascade fires, to see whether `serviceType_viSoln` briefly enters
`pending_variables` and gets dropped, or never enters it at all.
