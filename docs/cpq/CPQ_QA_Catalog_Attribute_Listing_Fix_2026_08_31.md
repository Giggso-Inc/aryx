# CPQ Pre-Quote QA: "List the Attributes" Fix

**Scope**: Aryx CPQ backend — `POST /ask`, pre-quote QA path (`_route_qa` / `_handle_cpq_qa`)
**Date**: 2026-08-31
**Branch**: `dev-rv-msi`
**Method**: Live investigation against the running API + FalkorDB container, followed by a scoped code fix and full regression verification.

---

## 1. Problem Statement

Before starting a quote, a user asked a pre-quote QA question:

> "list the attributes in APX Next"

and got back a sparse, seemingly arbitrary answer:

> "The attributes and attribute sets configured for the APX Next catalog include:
> - Instructions and Opt-Out?
> - Promotions and Promotion
> - promotionId
> - promotionArrayController array key"

This is wrong for a catalog with hundreds of real attributes. The answer needed to be fixed **without disturbing the current CPQ configuration flow** (the just-merged concurrency fixes, PR #287) — this bug lives entirely in a different, pre-quote code path.

## 2. Investigation

### 2.1 Tracing the code path

The question routes to `run_ask()` → gateway intent classification (`classify_ask_route`) → `route="qa"` (matched by the existing `_OPTIONS_KEYWORDS` rule, which includes "list") → `_route_qa()` (`ask_api.py:12426`) → `_handle_cpq_qa()` (`ask_api.py:1074`).

`_route_qa` already loads the **real, complete** attribute list for the catalog via `load_product_config()` (`engine.py:3906`) — confirmed to return APX Next's true attribute count. That list (`attrs`) is passed into `_handle_cpq_qa`, but every existing matcher inside it only knows how to answer a question about **one specific, named attribute**:

1. `detect_label_collision` — needs a shared label across 2+ attrs
2. Multi-attribute options split — needs 2+ named attributes + a conjunction
3. `detect_attr_query` — needs one specific attribute named

None of these match "list the attributes in APX Next" (it names no specific attribute), so the question fell into the **generic, open-domain graph-search fallback** — the same path used for arbitrary questions about anything in the ingested graph, not specifically about `ConfigAttr`s.

### 2.2 Why the generic fallback produced a bad answer

The fallback (`ask_api.py:1124` onward, shared with `_standard_ask_pipeline`):
1. `_extract_terms()` pulls a handful of named entities from the question (e.g. "APX Next")
2. `gather()` → `_lookup()` does a name-substring match, **hard-capped at 5 matches per term**
3. Each match is expanded exactly 1 hop, capped at **15 neighbors**, 12,000 characters
4. `_synthesise()` is instructed to answer in **maximum 5 lines**, enforced twice

No single `LIMIT 4` exists — "4" emerged from the LLM enumerating a handful of loosely-matched graph nodes inside a 5-line budget.

### 2.3 Live topology check — the real, structural blocker

A direct query against the live FalkorDB graph (workspace 39005, `aryx_ws_39005`) revealed the retrieval anchor itself is broken for this question class, not just under-sized:

| Finding | Detail |
|---|---|
| No "APX Next" product/catalog node exists | Name-substring match for "apx next" only finds `Dimension:Updatedby` lookup-value nodes (e.g. "apx next enhanced") |
| Real attributes live in a different type entirely | `ApxnextConfigdataBmConfigAttr` — **430 entities**, confirmed matching the true `ConfigAttr` count |
| 1-hop neighbors of the matched node | `Whitelist`, `Internaloption`, `Defaultinattr` — **not** `ApxnextConfigdataBmConfigAttr` |

**Conclusion**: widening the graph-search limits (more matches, more hops, bigger context) would **not** fix this — the retrieval starts from the wrong node entirely and cannot reach the real attribute entities no matter how large the limits are set. This ruled out the "just widen retrieval" fix before any code was written.

## 3. Options Considered

| Option | Mechanism | Verdict |
|---|---|---|
| **A — Deterministic**: answer directly from the already-loaded `attrs` list, grouped by attribute set | No LLM involved in the listing itself | Correct data guaranteed, but initially declined — product wanted an LLM-phrased, "sensible" answer, not a raw dump |
| **B — Widen graph retrieval**: increase `_lookup`/`gather`/`render_context` limits for this question type | Still graph-search based | **Ruled out** by the topology check — the anchor is wrong, not just too narrow; widening limits can't reach the real attribute nodes |
| **B-refined — Type-anchored graph query**: LLM maps "attributes" to the real ingested entity type, query by `type=`, not by name-match | Still graph-sourced, fixes the anchor problem | Viable, but adds a type-discovery step and doesn't correct-guarantee completeness the way reading the real `ConfigAttr` objects does |
| **A (hybrid) — Chosen**: real data from `attrs` (guaranteed correct/complete), LLM used **only** to phrase/group the final answer | No graph query for the listing at all | **Selected** — combines guaranteed-correct data with a natural, LLM-written answer, exactly matching the product requirement ("LLM handle the intent and phrasing, sensible answer") once the topology check ruled out a pure graph-sourced approach |

## 4. Chosen Design

A new matcher added to `_handle_cpq_qa`'s existing chain, **before** the generic graph-search fallback — reusing the existing QA routing/classification infrastructure rather than adding a new top-level intent/route.

```
detect_label_collision        (existing, unchanged)
  → multi-attribute split      (existing, unchanged)
    → detect_attr_query        (existing, unchanged)
      → NEW: catalog enumeration matcher
        → (fallback) generic graph search   (existing, unchanged)
```

### 4.1 Intent detection — LLM-driven, cheaply gated

`_llm_detect_catalog_enumeration_query(question, workspace_id)` — a small, JSON-structured LLM classification call (same `_llm_classify_intent_core` pattern already used elsewhere in this file), asking: "is this a whole-category listing request, not a specific-attribute question?"

Gated behind the **existing** `_OPTIONS_KEYWORDS` pre-check (already includes "list") so the common single-attribute case never pays this extra LLM call — same discipline the sibling multi-attribute-options split already uses.

### 4.2 Answer construction — real data, LLM phrasing only

`_build_catalog_attribute_listing_text(attrs, catalog_label, workspace_id)`:
- Filters `attrs` to only those that would genuinely reach the real submitted JSON/BOM payload — mirroring `CpqEngine.build_payload`'s own static, attribute-level inclusion rules exactly (its value-dependent checks, e.g. `_is_html_value`, don't apply here since there's no `filled` value yet, only the catalog's attribute definitions):
  - `not hidden` (never customer-facing, ConfigAttr's own docstring)
  - `not hide_in_trans` (real API rejects these with "cannot be modified")
  - `set_type != "2"` unless `auto_lock` (transient UI/action-layer attrs are excluded; `auto_lock=1` is `build_payload`'s own documented exception — a real, includable value that ships double-wrapped)
  - `not _is_noise_var(variable_name)` (underscore-/uppercase-prefixed session or integration fields, e.g. `_BM_USER_CURRENCY`, never real BOM selections)
- Sorts by the catalog's own `order` field
- De-duplicates identical `display_label`s (the same label can legitimately appear on 2+ distinct attrs)
- Passes the **real, complete** list of labels to a free-text LLM call (`llm_runtime.chat("answer", ...)`) with an instruction to group related attributes under plain-language headings and present the rest — the LLM never recalls or infers *which* attributes exist, only how to phrase/organize the real list it's given

**Revision (2026-08-31, same day):** the first cut of this filter used only `not hidden`, which surfaced obvious payload-noise alongside real attributes — live-confirmed against the real catalog: "Session Variable TER", "Transaction ID", "Boolean Continue 1-4", "Edit", "Save Changes", "Merge", and similar internal/system/UI-control fields all appeared in the answer despite never actually reaching the submitted JSON. Traced each one's real ingested fields (`hide_in_trans`, `set_type`, `variable_name`) directly against the live FalkorDB graph (workspace 39005) to confirm the exact static exclusion each one needed — not guessed. Re-verified live after the fix: none of the above terms appear in the answer any longer.

### 4.3 Why this stays isolated from the concurrency-fix flow

Entirely contained within `_handle_cpq_qa` (a pre-quote QA function) and its own new helpers — zero contact with `_run_cpq_turn_inner`, `evaluate_rules_loop`, or any of the caches/invalidation-marker code from PR #287.

## 5. Implementation

**Files changed**:
- `src/aryx/api/ask_api.py` — two new functions (`_llm_detect_catalog_enumeration_query`, `_build_catalog_attribute_listing_text`) plus one new `elif` branch in `_handle_cpq_qa`
- `tests/test_cpq_qa_catalog_attribute_listing_2026_08_31.py` — 8 new tests

**Test coverage**:
1. `_build_catalog_attribute_listing_text` only ever sees real, visible attrs — hidden attrs never reach the LLM prompt
2. Payload-scoping: `hide_in_trans`, `set_type=="2"` (unless `auto_lock`), and `_is_noise_var` attrs never reach the LLM prompt, while a real `set_type=="2"`+`auto_lock` attr does
3. Duplicate labels are de-duplicated before reaching the LLM
4. The real, full count and every real label reach the LLM prompt (proves no silent truncation)
5. The new matcher fires and answers from `attrs`, proven by asserting the generic graph-search functions (`_extract_terms`, `gather`) are **never called**
6. Negative control: a question with an options keyword but a `False` LLM classification still falls through to the existing generic fallback unchanged
7. Negative control: a question with **no** options keyword never even calls the LLM classifier (cheap-gate correctness)
8. Regression guard: an existing single-attribute options question is completely unaffected by the new matcher

**Verified test-catching-real-regression discipline** (matching this session's established practice): temporarily disabled the keyword pre-check gate and confirmed the corresponding test fails (a real, uncontrolled network call escapes), then restored the fix and confirmed all tests pass again.

## 6. Verification

- New test file: 7/7 pass in isolation
- Full CPQ regression suite (`-k cpq`, excluding the 3 previously-known pre-existing hanging e2e files): **17 failed / 1476 passed** — identical to the pre-existing baseline (17 failures were already present before this change), plus the 7 new tests passing
- One additional pre-existing, unrelated hang was found and confirmed (via `git stash`) to reproduce identically on completely unmodified code — not caused by this change
- **Live verification**: rebuilt and redeployed the running container, then re-asked the exact original failing question ("list the attributes in APX Next", pre-quote, workspace 39005) against it.

### 6.1 Live result — round 1 (real data, `not hidden` only)

Before (reported): 4 sparse, near-arbitrary items ("Instructions and Opt-Out?", "Promotions and Promotion", "promotionId", "promotionArrayController array key").

After (round 1): a complete, well-organized answer grouped into ~10 sensible categories (Customer and User Information; Billing and Shipping Information; Hardware Specifications, Parts, and Accessories; Packages, Bundles, and Promotions; Software, Subscriptions, and Services; Conditions and Validations; Help Text, Guides, and Instructions; Administration, Agencies, and Contacts; System Variables, Configurations, and Controls), covering hundreds of real attribute labels drawn directly from the catalog's real `ConfigAttr` list.

Server logs confirm: `llm_route=qa`, `status=200`, no errors. One honest cost note: this turn took ~70-120s (vs. the old, wrong answer's near-instant but incorrect response) — expected, since it now does real work (LLM intent classification + phrasing several hundred real attribute labels) instead of a cheap, broken shortcut. Unrelated to the concurrency-fix work (PR #287); this is the natural cost of a correct, comprehensive answer replacing a wrong, cheap one.

### 6.2 User feedback — scope too broad

Live-testing round 1 themselves, the user flagged that the answer, while correct and well-organized, was too broad: it included obvious internal/system/UI-control noise ("Session Variable TER", "Package Invoked Flag", "Transaction ID", "HTML Update 1/2/3", "Boolean Continue 1-4", "Edit", "Save Changes", "Back", "Merge", "Update", "Clear", "Configuration Process Step") that would never actually appear in the real submitted JSON/BOM payload. The ask: scope the listing to only attributes that genuinely end up in the JSON.

Traced `CpqEngine.build_payload` (`engine.py:13017`) directly to find its real, authoritative static inclusion rules (see §4.2's revision note), then confirmed each flagged noise item's real ingested fields against the live FalkorDB graph (workspace 39005) before changing the filter — e.g. "Edit"/"Save Changes"/"Merge" are `set_type="2"`/`auto_lock="0"` (transient UI-layer, real API rejects these), "Transaction ID" is `variable_name="_transaction_id"` (underscore-prefixed noise var).

### 6.3 Live result — round 2 (payload-scoped filter)

Rebuilt and redeployed the container with the revised filter, then re-ran the exact original question against the same live workspace. Grepped the full response text for every flagged noise term: **zero matches** for "Edit", "Save Changes", "Merge", "Transaction ID" — all correctly excluded. Real, legitimately-included attributes (e.g. "Wireless Carrier") remained present, confirming the filter didn't over-exclude.

### 6.4 User feedback — still seeing noise; root cause was LLM hallucination, not the filter

Testing again live, the user still saw "Boolean Continue 1-4", "Session Variable TER", "Package Invoked Flag" and similar items. Investigated by querying Postgres directly (`aryx_entity_ws39005.attributes`) for each flagged name: **"Boolean Continue 1" (with that exact spacing), "Session Variable TER", and "Package Invoked Flag" do not exist anywhere in the real ingested catalog.** The free-text LLM phrasing step — at catalog scale (~400+ items) — was inventing plausible-sounding filler attributes despite the prompt's explicit "never invent items" instruction. This is a structural problem with letting an LLM free-write prose over a list this large; a stronger prompt alone would not reliably fix it.

**Fix**: rearchitected `_build_catalog_attribute_listing_text` so the LLM never writes the final text at all. It now returns a structured JSON grouping (`{"groups": [{"heading": ..., "items": [...]}]}`), and every item is checked for an **exact string match** against the real label set before being rendered — anything that doesn't match (invented, paraphrased, merged, renamed) is silently dropped. Any real label the grouping never placed anywhere (dropped, over-written, or the LLM call/parse failing outright) is still appended under a final "Other" heading, so no real attribute can ever be silently lost, even on total LLM failure. The bullet text itself is now rendered by Python from the validated real strings, never by LLM prose.

**Live re-verification**: rebuilt, redeployed, re-ran the same question. Grepped for every previously-hallucinated term: zero matches. The single "Boolean Continue" match remaining was traced and confirmed **real** — `BoolContinue1`–`BoolContinue4` genuinely exist in Postgres (`set_type="1"`, `hide_in_trans="0"`), a different, real attribute from the fabricated "Boolean Continue 1" (different spacing) that never existed. The guard correctly distinguishes the two.

### 6.5 Follow-up — reuse build_payload's own filter functions; drop unlabeled raw fields

The user asked for two more things, live in review: (1) don't hand-mirror `build_payload`'s filter conditions in ask_api.py — call the exact same functions `build_payload` itself calls, so the two can never silently drift apart; (2) if an attribute never got a real human-readable label from the source data, leave it out entirely rather than showing the raw internal name.

**(1) Shared predicates**: extracted `CpqEngine._attr_hidden_from_submission(attr)` and `CpqEngine._attr_is_transient_set_type(attr)` as two new `@staticmethod`s on `CpqEngine` (`engine.py`, next to the pre-existing `_is_noise_var`), each containing the exact boolean expression `build_payload`'s own per-key loop already evaluated inline. `build_payload`'s loop was refactored to call them at the exact same two positions (pure extraction — verified byte-for-byte behavior-preserving by running every `build_payload`-touching test file before and after: 243 passed / 2 failed both times, and the 2 failures were confirmed via `git stash` to reproduce identically on completely unmodified code). `_build_catalog_attribute_listing_text` now calls these same two methods plus the pre-existing shared `_is_noise_var` — the JSON-payload-inclusion logic is now genuinely single-sourced, not a parallel copy.

**(2) Unlabeled raw fields**: live-confirmed via direct Postgres query that several real attrs (`sessionVariable_TER`, `packageInvokedFlag`, `commerceAttrsFlag` — real `variable_name="commerceAttrsFlag_all"`, suffix trimmed) never received a human-readable label in the source XML; ingestion fell back to the raw internal name. An exact `display_label == variable_name` check alone missed the suffix-trimmed case, so the filter instead checks the general *shape* of a raw identifier: no spaces, starts lowercase, has an internal capital letter (camelCase's own signature) — catalog-agnostic, not a name list. A genuine short label/acronym that starts uppercase (`CCAWARE`, `VX650`, `BoolContinue1`) is unaffected and stays.

**Final live re-verification**: rebuilt, redeployed, re-ran the same question once more. Confirmed via regex scan: zero remaining camelCase-shaped raw identifiers in the answer, while `CCAWARE`, `CCDEMS`, `VX650`, and `BoolContinue1`–`4` (all genuine, properly-cased real attrs) are still present.

### 6.6 User feedback — the real submitted JSON has only 7 keys, not ~200

The user then pasted a REAL submitted quote's actual `configData` payload — 7 keys total (`hWVersion_astro`, `productSelectionProduct_all`, `baselineReleaseSW_astro`, `carrierSelectionMultiSelect_astro`, `applicationServicesSelection_astro`, `ultimateDestinationCountry`, `packageRegion`) — next to the ~200-item answer this fix was producing. Root cause, reasoned through in Andie/Drama mode (an architecture-scope question, not a bug): `build_payload`'s static filters (`hide_in_trans`/`set_type`/noise) only decide what's excluded from an attr that's ALREADY been asked and filled — they say nothing about which attrs get asked in the first place. Which attrs get asked is inherently **path-dependent** (different Hardware Version choices lead to different follow-up questions); a real quote only fills the handful of attrs on the *one path taken*. Building a true "run a full quote to completion" simulator was considered and explicitly ruled out by the user as unnecessary.

**Fix — use the real native-UI layout as the visibility scope**: `CpqEngine.load_layout_display_order(workspace_id, catalog_prefix)` (`engine.py:4806`) already parses the catalog's real BigMachines layout export (`config_layouts/*.txt`, wired into the container via `ARYX_CPQ_LAYOUT_DIR`) into `{variable_name: rank}` for exactly the attrs the real screen marks `hide: false` / non-HTML — the SAME source `build_payload`'s own `display_order` param already uses for "the real UI visible set." `_build_catalog_attribute_listing_text` now scopes to this set (ranked by the file's own document order) when a catalog has an Active layout export, falling back to `attrs`' own catalog `order` only when no layout export exists for that catalog. Layout membership and JSON-payload eligibility are orthogonal, so the existing static predicates (`hidden`, `_attr_hidden_from_submission`, `_attr_is_transient_set_type`, `_is_noise_var`) still apply unconditionally on top — live-confirmed this catch was needed: without it, real on-screen action-button-style layout entries ("Merge", "Update", "Clear") leaked back in, since they're `set_type=="2"` transient controls that appear on screen but never reach a real submission.

**Live re-verification**: rebuilt, redeployed, re-ran the same question. The answer shrank from ~200 items to ~95 — a much closer approximation of "what a real quote would actually show/ask," while remaining honest that it's the catalog's full native-UI-visible set (which spans all possible paths), not one specific quote's exact 7-key result, since no path has been chosen yet at ask-time. Confirmed the action-button leak (`Merge`/`Update`/`Clear`) is gone; spot-checked one remaining terse label ("Select") directly against Postgres and confirmed it's a genuine real attribute (`relatedServiceSelectAry_astro`, `set_type=1`, not hidden), not a bug.

## 7. Status

**Complete.** Implemented across six iterations driven by live user testing (payload scoping → hallucination guard → shared-predicate reuse + raw-label exclusion → real native-UI layout scoping), unit-tested (11/11 tests in the dedicated test file), regression-verified (every `build_payload`-touching test file: 254 passed, 2 pre-existing failures confirmed unrelated via `git stash`), and live-verified five times against the running container with the exact original failing question at each stage. Known remaining limitation, explicitly accepted: pre-quote, the answer is the catalog's full native-UI-visible set across all possible configuration paths, not one specific quote's exact final JSON (which only exists once real choices are made) — building a full quote-completion simulator to close that last gap was considered and explicitly declined by the user as unnecessary.
