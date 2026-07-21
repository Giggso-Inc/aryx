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
this file).

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
