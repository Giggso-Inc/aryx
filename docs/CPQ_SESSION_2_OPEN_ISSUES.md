# CPQ Open Issues — Not Yet Fixed (as of dev `6c3e8b2` / feature/msi_cpq `1cc5c1e`)

Cross-checked every item in `CPQ_SESSION_2_MASTER_ISSUES_AND_FIXES.md`
against the latest `dev` merge (PR #107 — select-model/summary-noise
fixes) to confirm current status. Confirmed **fixed** since last review:

- Item 2 (`skip_always_ask` for product-identifier attrs) — original
  broad fix reverted for a real regression, replaced with a narrower,
  correctly-scoped version. Net intent still fixed.
- Item 5's original bug (compound-label/free-text-quantity matching) —
  fixed, PLUS a follow-up sibling-attribute number-mixing bug in the
  same code found and fixed.
- Base Model/Select Model no longer wrongly force an always-ask for
  catalogs where it shouldn't (user-confirmed: "dev is working properly
  without asking model and product name").
- A hidden-attr summary-visibility bug adjacent to item 7 (user-answered
  grid-quantity attrs silently missing from summaries).

This file lists only what is **still open** — see the master doc for
full history, commit references, and the items already closed above.

---

## 1. Change-request matcher can't handle a REORDERED phrase (item 5's residual gap)

**Problem:** "change the quantity of jacket magnetic mount" (quantity
named BEFORE the mount, reversed from the attr's own label word order —
"mounting type Jacket Magnetic Mount Quantity") still falls through to
"I didn't quite catch that." The matcher (`_label_mentioned`/
`_label_mention_span`) only tolerates DROPPED leading words, never
reordering — confirmed still true after dev's latest fix in this same
function family (`c570bf4`), which fixed a different bug (sibling-attr
number mixing) without touching word order.

---

## 2. Product-switch confirmation swallows a NEW switch mention as a flat decline

**Problem:** [ask_api.py:900-943](../src/aryx/api/ask_api.py) — when a
switch-confirmation prompt is pending and the reply doesn't affirm the
CURRENTLY pending product, it's unconditionally treated as "no, stay,"
even if the reply itself names a different, real product. Confirmed
live: after DM4400 triggered a pending switch prompt, "Quote APX Next
Enhanced radios..." — itself a clear switch request — got swallowed as
"OK — continuing with videoSolutions_BOM" instead of being recognized.
Proposed fix (re-run `detect_product_mention` before declining) was
scoped but implementation was explicitly stopped mid-way by request —
not started.

---

## 3. Mounting Type array construction has no deterministic BML evaluator tier

**Problem:** `mountingTypeArray_viSoln`'s per-option derived attrs
(boolean flags, quantity rollups) are populated by a native BML script
using a `range(control_attr)` + `selector[idx]`/`qty[idx]` array-iteration
idiom `BmlEvaluator` has no tier for — always falls to the slow/
non-deterministic LLM Tier 2 or times out unresolved. Confirmed
recurring across all 3 available catalogs (SVX, APX NEXT/DM4400,
SL3500e — 124/162/74 subscript reads respectively). Full plan written
(`CPQ_BML_ARRAY_ITERATION_TIER_PLAN.md`, two approaches scoped:
runtime evaluator tier vs. ingestion-time graph enrichment) — not
implemented. Note: a related but DIFFERENT bug (hidden-attr summary
visibility) in this neighborhood was fixed by dev's `5c5a445`; the
evaluator gap itself is untouched by that fix.

---

## 4. No persisted session memory across product switches

**Problem:** Switching products mid-session (A → B → C → back to A)
still discards each product's in-progress answers by design — confirmed
intentional scope cut, not a technical wall, and no DB-backed session
store exists (client-held JSON blob only). Full plan written
(`CPQ_MULTI_PRODUCT_SESSION_SNAPSHOT_PLAN.md` — `product_snapshots`
dict, restore via `auto_fill`'s existing re-validation path, capped at
5 entries, country-precedence traced and confirmed conflict-free) — not
implemented.

---

## 5. Duplicate attribute labels — display AND query-resolution both affected

**Problem:** Multiple, functionally distinct attributes across catalogs
share an identical display label in the native XML — confirmed 3
collision groups in a single APX NEXT quote alone (a 3-way "Service
Type" collision, plus "Duration" and 'Is this a "SPARE radio"' pairs),
not just SVX's "Mounting Type." Beautify/summary rendering shows
indistinguishable duplicate rows, and `detect_attr_query`'s
identical-length tiebreak resolves an ambiguous options-query
arbitrarily rather than asking. Checked the native BigMachines editor
screenshots and `ConfigAttr`'s own fields directly: no rep-visible
disambiguating field exists (variable_name and admin metadata are
backend-only, never shown to an actual quoting rep). Two-part fix scoped
(display: `variable_name` suffix on collision; query: reuse the existing
`suggest_switch` clarify-before-guessing pattern, listing candidates by
current value) — not implemented.

---

## 6. `mountingArrayControl_viSoln` value doesn't match the actual quantity entered

**Problem:** Live transcript (SVX, Locking Molle Mount, quantity "7"):
`mountingTypeLockingMolleMountQuantity_viSoln` correctly shows `7`, but
`mountingArrayControl_viSoln.items[0].value` shows `"5"` — the array
Configurable Attribute Set's own size/control attribute doesn't reflect
the row's real quantity. Not yet root-caused — unclear whether dev's
`c570bf4` sibling-attribute fix (a different code path: change-request
number extraction, not the direct-answer path this transcript used)
incidentally affects this; needs a live-session repro to confirm either
way, not yet done.

---

## 7. Cascade-invalidated non-hidden attribute silently vanishes; flow still claims "Configuration complete"

**Problem:** Picking a new Mounting Type cascades and correctly
invalidates `serviceType_viSoln`'s prior answer ("Removed TECH SUPPORT
AND HARDWARE REPAIR from Service Type"), but the attr is never re-asked
and disappears from both the summary and the final payload — confirmed
via raw XML it is NOT hidden (`hidden=0`) and NOT suppressed by the
active Solution Type condition (that rule targets a different attr,
Service Duration). Despite this, the flow declares "Configuration
complete" and offers submission with a real, previously-answered
decision silently missing. Not yet root-caused — suspected gap in how
`_handle_cascade`'s invalidation interacts with the completeness check
that decides "complete" vs. "N attributes still need input," not yet
traced against a live session.
