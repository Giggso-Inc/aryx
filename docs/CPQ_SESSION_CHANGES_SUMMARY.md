# CPQ Session Changes — Problem Statements & Fixes

All changes made in this session on `feature/msi_cpq`, workspace 19 (SVX / APX Next Enhanced / SL3500e / DM4400 catalogs), in chronological order.

---

## 1. `skip_always_ask` never reached the real "pending" computation
**Commit:** `b2f2b77`

**Problem:** The engine had logic to suppress asking `productSelectionProduct_all` for catalogs where the native UI never shows it (e.g. SVX), but the field was still being asked anyway.

**Fix:** `skip_always_ask` was only passed to `evaluate_rules_loop`, not to the separate `auto_fill()` call in `ask_api.py` that actually computes the list of questions shown to the user. Passed it to both call sites.

---

## 2. "Select Model" menu missing due to a graph-ingestion gap
**Commit:** `f6baab5`

**Problem:** SVX's "Select Model" panel (and SL3500e's country picker) never appeared as a question — their option lists loaded empty even though the attributes existed.

**Fix:** The real menu data existed correctly in Postgres (linked via `bm_config_attr_id`), but the corresponding FalkorDB graph edges were missing. Added a Postgres-FK fallback in `load_product_config` that recovers options structurally (by graph flags, not catalog/attr name) when no graph edge exists. Also fixed two follow-on bugs discovered while shipping this: a bulk-fetch that silently truncated at 2,000 rows on large catalogs (added pagination), and duplicate-ingested graph entities that could drop one copy's options (fixed the id-to-owner mapping from 1:1 to 1:many).

---

## 3. `productSelectionProduct_all` leaking a cross-catalog value
**Commit:** `e83791c`

**Problem:** SVX quotes were filling `productSelectionProduct_all` with `"APX6500"` — a foreign, APX-family product code — even though the field was supposed to be suppressed for SVX.

**Fix:** Suppressing the *ask* for this field also unintentionally unlocked a "blind first-by-order" auto-fill fallback meant for other governed attrs, and separately the fallback question list never checked the suppression flag on its own either. Closed both gaps.

---

## 4. Flat "Key decisions" summary was hard to scan
**Commit:** `23bfb3b`

**Problem:** The end-of-quote summary was one long flat bullet list mixing product info, service terms, quantities, and everything else together.

**Fix:** Added a generic, pattern-based classifier grouping the summary into 4 sections — Product Name, Service Plan, Quantity & Duration, Associated Options — driven by variable-name fragments, not per-catalog literals.

---

## 5. FalkorDB pagination had no stable row order
**Commit:** `b3813e6`

**Problem:** Raven code review flagged that the new pagination fix (item 2 above) added `SKIP`/`LIMIT` to the FalkorDB query without an `ORDER BY`, risking silently skipped or duplicated rows across pages on large catalogs — reintroducing the exact bug it was meant to fix.

**Fix:** Added `ORDER BY e.id` to the FalkorDB query, mirroring the Oracle reader's existing `ORDER BY entity_id` for the same reason.

---

## 6. Product-identifier attrs could still silently guess wrong
**Commit:** `445595b`

**Problem:** In a multi-product-switch conversation, `modelSelectionSelectModel_viSoln` (SVX's "Select Model") resolved to `"V200 Body Worn Camera"` — an unrelated accessory — instead of the real SVX model, because its option list mixes unrelated products and the same "blind first-by-order" fallback from item 3 fired again on a different attribute.

**Fix:** Extended the existing "Product Name" fragment classifier into a shared signal used by `auto_fill`'s decision-attr logic — any attr that names the product/model itself is now asked (never silently guessed) when no hint or rule resolved it. Also dropped `"(none)"` placeholder entries from the categorized summary in the same commit.

---

## 7. A genuine switch-intent sentence got swallowed as an answer
**Commit:** `f199146`

**Problem:** Conversation history showed "Quote APX Next Enhanced radios for a US customer." — while a different catalog's Product question was pending — silently locked in `"APX NEXT ENHANCED"` as the answer to the *wrong* catalog's Product field, instead of prompting to switch. No switch prompt, no valid Product ever chosen.

**Fix:** `productSelectionProduct_all`'s option list is shared/catalog-wide, so the switch sentence legitimately option-matched against the wrong catalog's copy of the same list. For this attribute specifically, switch-detection now runs before trusting an option-match as a real answer — unless the reply is an *exact*, standalone match to one of the attribute's own options (preserving an earlier, different fix for a similar false-positive).

---

## 8. LLM-narrated summary reverted to a flat paragraph
**Commit:** `e387f22`

**Problem:** Item 4's categorized format only applied to the deterministic bullet fallback. When the LLM provider was actually reachable, the summary reverted to a plain, uncategorized paragraph.

**Fix:** Extracted the categorization logic into a shared, public method (`categorized_summary_groups`) used by both the deterministic fallback and the LLM prompt, so the LLM narrates within the same fixed categories instead of inventing its own organization.

---

## 9. The real product name was hidden from every summary
**Commit:** `4532590`

**Problem:** Even after items 4/8, `productSelectionProduct_all` (the actual, correctly-filled product — e.g. `"APX NEXT Enhanced"`) never appeared under "Product Name" — only the internal Base Model code showed.

**Fix:** A pre-existing filter blanket-excluded anything with "product" in its name from the summary, on the assumption that the summary's header already names the product — but the header shows the internal BOM codename, not the real product name. Exempted this one attribute specifically from that exclusion; every other product/product-line noise attribute it targets stays excluded.

---

## Verification

All 9 changes were verified live against the local Docker container and workspace 19's real graph data, and passed the full targeted test suite (`test_cpq_e2e.py`, `test_cpq_product_switch.py`, `test_cpq_model_pointer.py`, `test_ports_seam.py`, `test_cpq_engine_catalog_scope.py`, `test_cpq_grid_decline.py`) with no new regressions beyond the pre-existing, unrelated failures already present before this session's changes.
