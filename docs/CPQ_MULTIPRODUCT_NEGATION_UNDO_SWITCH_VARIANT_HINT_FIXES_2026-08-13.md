# CPQ Ask — MultiProduct/Negation: Undo-vs-Switch Collision & Variant-Only Hint Miss

**Branch:** `fix/cpq-multiproduct-negation-undo-switch-and-variant-hint`
**Base:** `dev-rv` (enterprise)
**Source:** manual test run via Andie against `/ask`, results in `cpq_test_cases.xlsx`
**Sheets analyzed:** `6-MultiProduct`, `7-Negation`
**Real catalogs used for verification:** `APX_next.xml`, `SVX.xml` (user-provided)
**Constraint:** no new regex, no hardcoded product/value list — every fix reuses or
generalizes existing dynamic, catalog-driven logic.
**Date:** 2026-08-13

## Summary

Of 20 rows across the two sheets, 2 failed — one per sheet. Both are real code bugs,
both fixed.

| Test ID | Sheet | Detector | Failure mode | Status |
|---|---|---|---|---|
| MT17 | 6-MultiProduct | `run_cpq_turn` | undo swallows a named product switch | Fixed |
| N04 | 7-Negation | `catalog_hints` | variant-only phrasing never matches | Fixed |

## Bug 1 — MT17: "go back" collides with naming a real product

**File:** [`src/aryx/api/ask_api.py:6306-6337`](../src/aryx/api/ask_api.py)

**Input:** `Actually go back to APX NEXT` (mid-session, currently configuring MOTOTRBO)
**Expected:** offer a `confirm_switch` back to APX NEXT
**Actual (before fix):** treated as `cpq_undo()` — rolled back one snapshot, product
name unaffected, the named product ignored entirely

**Root cause:** `_run_cpq_turn_inner` checks `detect_undo(req.question)` unconditionally
near the top of the function, before any other routing — the comment even says so:
*"First-class UNDO — restore last session snapshot before any other routing."*
`_UNDO_RE` (`session_guard.py:42-45`) treats `undo|revert|roll back|go back|previous
state` as undo triggers. "go back" is also the single most natural way a customer says
"switch back to a product I was on before" — two unrelated features claim the same
everyday phrase, and undo wins by pure code order, discarding the product name entirely.

**Fix:** when `detect_undo` fires, also call the existing `_safe_detect_product_mention`
helper (`ask_api.py:161-171`) — the same dynamic, catalog-driven detector every other
switch-detection call site in this file already trusts (no hardcoded product list; it
reads real ingested product/family names from the graph). If it returns a product name
different from the session's current product, the undo return is skipped and execution
falls through to the pre-existing switch-detection logic further down the function
(`ask_api.py:~7515`, `cpq_switch_candidate()`), which correctly offers the confirmation.
A lookup miss or failure degrades to `""`, falling through to today's plain undo
behavior exactly as before — nothing about undo itself changed for ordinary "undo"/
"roll back"/"go back" messages that don't also name a product.

**Why not a regex fix:** the tempting shortcut — special-case a phrase like `"go back
to <product>"` — would be exactly the kind of narrow, phrase-specific patch the task
explicitly ruled out, and would need updating every time a new phrasing variant showed
up. Reusing `detect_product_mention` means *any* real, ingested product name mentioned
alongside *any* undo-trigger phrase is now handled correctly, for every catalog, with
zero new pattern text.

## Bug 2 — N04: naming only the distinguishing variant never matches

**File:** [`src/aryx/cpq/engine.py:939-961, 1483-1524`](../src/aryx/cpq/engine.py)

**Input:** `I'll take the 4G LTE+5G version`
**Expected:** `NEXT ENHANCED LTE PLUS 5G` (the real `hWVersion_astro` item_value)
**Actual (before fix):** `(none)`

**Root cause:** `extract_catalog_hints`' D2 "never guess" rule requires the *whole*
glued option text (item_value or display_name) to appear verbatim in the question. The
real `hWVersion_astro` option in `APX_next.xml` has `display_name = "APX NEXT (4G
LTE+5G)"` — a common family name outside the parens, the specific variant inside.
Naming only the variant — the most natural way to answer "which hardware version?" — is
missing the "APX NEXT (" / ")" wrapper, so the whole-string match silently fails and the
attribute is left unfilled.

**Fix:** added `_parenthetical_suffix(text)` — plain string parsing (`rstrip`,
`endswith(")")`, `rpartition("(")`, `strip()`; no `re` module, no pattern list) that
extracts the inner `(...)` content of a trailing parenthetical segment. This is exposed
as an *additional* candidate text alongside `item_value`/`display_name` in
`extract_catalog_hints`' existing candidate-building loop, so it flows through the exact
same ambiguity, negation, and never-guess machinery every other candidate already uses —
this is a structural widening of *what counts as candidate text*, not a new rule engine,
and it works for any catalog option shaped this way in any workspace, not just this one
product.

**Real ambiguity found and closed while building this:** grepping `APX_next.xml` found
that both `"APX NEXT (4G LTE+5G)"` and `"APX NEXT XE (4G LTE+5G)"` exist as real sibling
options (different `bm_menu_item`s, same `ref_id`, i.e. a `productSelectionProduct_all`-
style attribute) sharing the identical parenthetical suffix. The pre-existing ambiguity
guard (`if len(owners) > 1: continue`, deduplicating by variable_name only) does **not**
catch this if both ever land in scope under variable_names that happen to collapse to a
single owner set — reproduced live with a synthetic same-attribute case, which the old
code silently resolved to the wrong item (a guess). Strengthened the guard: added
`if len(set(entries)) > 1: continue`, rejecting whenever 2+ *distinct real values* (not
just 2+ distinct attrs) share a phrase. This check is strictly more conservative than
the old one — it can only add rejections, never remove one — so it cannot regress any
previously-passing case; verified via the full 7-Negation sheet replay (0 mismatches)
and dedicated tests.

**Cross-catalog verification (`SVX.xml`):** the same `"X (Y)"` display-name convention
appears repeatedly (`"Conventional (CDEM)"`, `"1 Year (Standard)"`, `"UHF (403-470
MHz)"`, `"Spare Battery Charger (desktop or In-vehicle)"`, several country names). Used
this to confirm the fix generalizes rather than being overfit to one catalog's exact
text.

## Independent review and its findings (both fixed before this PR)

An independent `code-reviewer` pass on the first draft caught 2 real issues:

- **MEDIUM** — a parenthetical suffix is a much shorter, more generic-sounding fragment
  than the full option text it's plucked from. `"Best Value"` or `"desktop or
  In-vehicle"` read like ordinary prose, unlike a full catalog-specific
  item_value/display_name — multi-word alone isn't strong enough distinctiveness
  evidence for an isolated fragment the way it is for the full text. **Fix:** a
  parenthetical suffix must now *also* look like a technical code (contains a digit or
  `/`) before being trusted as a candidate — `"1 Year (Standard)"` and `"Conventional
  (CDEM)"` correctly stay unresolved; `"APX NEXT (4G LTE+5G)"` and real APX_next.xml
  frequency-range options (`"UHF (403-470 MHz)"`) still resolve.
- **LOW** — `_parenthetical_suffix` mishandled nested/unbalanced parens: `rpartition("(")`
  finds the *last* `"("`, so a hypothetical `"APX (FOO (BAR))"` would have silently
  produced a corrupted `"BAR)"` fragment. **Fix:** now returns `None` (never a candidate)
  whenever the extracted inner content still contains `"("` or `")"`.

## Verification

- Replayed both sheets (10 + 10 rows) against the fixed code — the 2 failures now pass,
  all 18 prior passes unchanged.
- 10 new tests: 3 in `tests/test_cpq_product_switch.py` (MT17 fix + 2 non-regression
  cases: plain undo with no product named, undo naming the *current* product), 7 in the
  new `tests/test_cpq_catalog_hint_parenthetical_variant.py` (N04 fix, the ambiguity
  guard against real cross-product collision data, negation interaction, no-parens
  no-op, cross-catalog SVX generalization including the tightened code-marker rule, and
  the nested/unbalanced-parens helper edge cases).
- Full CPQ suite: **1072 passed, 47 skipped, 0 failed** (pre-existing, unrelated
  collection/network issues already documented in this repo's history excluded, as
  before).

## Files changed

- `src/aryx/api/ask_api.py` — undo-vs-switch disambiguation
- `src/aryx/cpq/engine.py` — `_parenthetical_suffix` helper + `extract_catalog_hints`
  candidate widening and strengthened ambiguity guard
- `tests/test_cpq_product_switch.py` — 3 new tests
- `tests/test_cpq_catalog_hint_parenthetical_variant.py` — new file, 7 tests
