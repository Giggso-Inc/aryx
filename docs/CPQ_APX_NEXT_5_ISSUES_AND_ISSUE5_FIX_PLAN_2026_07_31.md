# APX NEXT CPQ — Today's 5 Confirmed Issues + Fix Plan for Issue 5

Session date: 2026-07-31 · Scope: aSTRO25_bom (APX Next catalog), workspace 21 · Companion to `APX_NEXT_CONFIG_CONSISTENCY_REVIEW.docx` (full detail, XML citations, and appendices live there — this document is the condensed standalone version plus the fix plan).

---

## Issue 1 — Cascade-invalidated attributes survive into the final "complete" state

**Problem:** After changing Frequency Bands to VHF, the engine announces the old 700/800 MHz value and the old Carry Type value as "no longer valid — removed" — but the same turn's final state table and JSON still show both old values unchanged, and the configuration is declared complete regardless.

**Root cause:** The invalidation-announcement step and the final-state-rendering step read from two different snapshots of session state rather than one consistent source of truth. Confirmed via raw catalog cross-check that the underlying catalog data is clean (16/16 sampled attribute values matched valid catalog options) — this is a state-consistency bug in the engine, not bad reference data.

**Status:** Superseded/absorbed by Issue 4's deeper trace (same symptom family, fully root-caused there).

---

## Issue 2 — Software Bundles: only 1 of ~24 real options surfaced

**Problem:** Asking "what are the options for software bundles?" returns only the currently-selected bundle ("Core Trunking Bundle"), not the real ~24-option menu.

**Root cause (hypothesis, not code-traced):** The Q&A "options for X" handler, for a multi-select attribute, likely returns the customer's current answer (`session.filled_multi`) instead of the attribute's full option list.

**Status:** Root-caused as a hypothesis; not yet fixed. One related observation (a suspected "Standard Bundle vs Core Bundle" field mismatch) was investigated and retracted — confirmed via raw XML that pairing is catalog-valid.

---

## Issue 3 — Wireless Carrier wrongly pulled into a "Frequency Bands" label-collision prompt

**Problem:** Asking "what are the Frequency Bands and Wireless Carrier available?" triggers a 3-way disambiguation that wrongly includes `wirelessCarrier_astro` alongside the real Frequency Bands attributes.

**Root cause — CONFIRMED:** Direct catalog label lookup shows zero textual overlap between "Wireless Carrier" and any of the three real "Frequency Band(s)" labels, and no shared UI grouping either. This is a candidate-matching bug in application code (likely fuzzy/embedding-style overlap against the query text), not a catalog data issue.

**Status:** Root-caused, not yet fixed.

---

## Issue 4 — Repeated re-ask loop: the same Frequency Bands/Carry Type question asked 3+ times across confirm attempts

**Problem:** Across two independent live transcripts, customers were forced to answer the same "Frequency Bands" and/or "Carry Type" question multiple times across consecutive `confirm` attempts, each time told their already-corrected answer was still invalid, before the BOM gate let the configuration through. In one transcript, Carry Type failed the gate on the very FIRST confirm — before the customer touched anything.

**Root cause — CONFIRMED (raw XML + code trace):**
- Two recommendation rules ("Default Values...Package Type FIXED/SEMI-FIXED") set Frequency Bands, Primary Frequency, and Secondary Frequency together as sibling outputs of one shared input variable (`packageChoiceString`, via a compiled `util.packageConfig()` lookup) — not derived from each other as originally hypothesized.
- If `packageChoiceString` stays stale at the old package selection while only Frequency Bands is changed directly, every re-fire of this rule overwrites all three attributes back to the old package's values in one shot.
- This explains both the repeat loop AND why Primary/Secondary Frequency were never corrected even after the loop broke (they were never the customer's actual target, just fellow-travelers of the same rule).
- The write-path itself (STEP 5 answer-locking in `ask_api.py`) was traced and confirmed NOT mistargeted at the wrong attribute — ruling out the simplest "bare reply lands in the wrong sibling" explanation for this specific symptom.
- Clarified: `bom_gate.validate_before_payload` never emits a payload while a check fails — every affected "confirm" returned a re-ask, not a submitted BOM with a bad value in it.

**Status: ✅ CONFIRMED FIXED**, live-verified against the container after pulling `origin/dev-rv` (27 commits, including PR #140 "fix/cpq-frequency-band-multiselect-collision"). Live re-test showed: first confirm goes straight through with no stale re-ask; a Frequency Bands change now cascades Primary/Secondary Frequency together correctly in one clean update; no repeated loop; final payload has all three attributes self-consistently set to the new value.

---

## Issue 5 — APX NEXT Enhanced (multi-band product): Aryx writes to the wrong sibling attribute across three attribute families

**Problem:** For a product on the multi-band side of the catalog (APX NEXT Enhanced, 4G LTE+5G), Aryx's generated payload disagrees with a known-correct, validated reference payload on at least three independent attribute pairs — Frequency Bands, Wireless Carrier, and a software-release flag — each time picking the wrong half of a mutually-exclusive attribute pair (or a deprecated legacy value).

**Root cause — CONFIRMED (raw XML):**
1. **Frequency Bands**: catalog rule "Hide Frequency Band & Extend Range if Product is selected as APX Enhanced" explicitly routes MULTI/XE MULTI/XN ALL/INTL FED/**APX NEXT ENHANCED** products to `modelSelectionFrequencyBandMsl_astro`, and Single-Band-family products to `modelSelectionFrequencyBands_astro`. Aryx emits the Single-Band fields for an Enhanced order and never populates the Msl attribute at all.
2. **Wireless Carrier**: live-tested, Aryx emitted `wirelessCarrier_astro="ATT/FIRSTNET"` — a SIM-carrier-style value that isn't a legal option for that attribute at all — strongly suggesting the value meant for the missing `carrierSelectionMultiSelect_astro` landed in the wrong sibling attribute, same pattern as #1.
3. **Software release flag**: `baselineReleaseSW_astro` has both a legacy boolean-style value ("YES"/"NO") and the current canonical pair ("BASELINE RELEASE"/"LATEST RELEASE"), both mapping to the same display text. Aryx picks the legacy "YES"; the validated reference correctly uses "LATEST RELEASE".

**Status: ❌ NOT FIXED.** Live re-verified after pulling and merging 31 more `dev-rv` commits (including "dependency-aware payload ordering + standalone-payload defaulting") and rebuilding the container — all three symptoms are still present, unchanged. The dev-rv work released so far targets Issue 4's mechanism (a stale-value gate re-check at confirm time), which is structurally different from this issue (a wrong-attribute-family selection at default-fill time, before any gate check runs).

---

## Fix Plan — Issue 5

### Diagnosis to confirm before writing code

The three symptoms share a suspicious shape: in every case, the catalog defines two (or more) legitimate representations of the same real-world attribute, gated by product family or by era (legacy vs. current), and the engine's default/auto-fill logic picks one without checking which one the CURRENT product/context actually calls for. Before touching code, confirm this is genuinely one shared code path and not three coincidentally-similar bugs:

1. Trace `engine.py`'s default-value / auto-fill resolution order for a menu attribute that has an active product-family-scoped hiding/constraint rule — does the resolver consult `hiding_rules`/`con_rules` for the ATTRIBUTE ITSELF before deciding to populate it, or only after (i.e., does it fill first and let a downstream hide-rule "clean up" second)?
2. Confirm whether `modelSelectionFrequencyBandMsl_astro` and `carrierSelectionMultiSelect_astro` are even present in `attrs` (the loaded attribute list) for an Enhanced-product session, or whether they're being filtered out earlier (e.g., by `skip_always_ask`, `product_label_noise_vns`, or a similar exclusion set) before the auto-fill pass ever gets a chance to consider them.
3. For `baselineReleaseSW_astro` specifically: check whether the default-value selection logic dedupes options by `item_value` uniqueness or by `display_name` — if two options share a display name ("Baseline Release" appears for both "YES" and "BASELINE RELEASE"), whichever the resolver iterates first (likely declaration order in the XML/DB) silently wins; this may be a simple "prefer the option whose value looks like the modern/canonical spelling" ordering fix rather than a hiding-rule gap.

### Proposed fix shape (pending the diagnosis above)

- **For the two attribute-family cases (Frequency Bands, Wireless Carrier):** the auto-fill/default-value path must resolve product-family-scoped hiding/constraint rules for BOTH members of a mutually-exclusive pair before choosing which one to populate — i.e., if a hiding rule would hide `modelSelectionFrequencyBands_astro` for this product, the resolver should route to `modelSelectionFrequencyBandMsl_astro` instead of defaulting `Bands` first and only hiding it after the fact. This likely means moving the hiding-rule check earlier in the evaluation order for attributes that are known to have a sibling, or adding an explicit "resolve mutually-exclusive attribute family" step before generic default-value fill.
- **For the legacy-value case (`baselineReleaseSW_astro`):** when multiple menu options share a display name, prefer the option whose `item_value` matches the attribute's own "current" convention (e.g., prefer a value that is NOT a bare "YES"/"NO" when a differently-spelled option with the same display text exists) — or, more robustly, prefer the option most recently added / highest `order` in the menu list if the XML's ordering reflects "supersedes."
- **Test coverage to add:** a regression test per attribute family — order an Enhanced/multi-band product and assert `modelSelectionFrequencyBandMsl_astro` is populated and `modelSelectionFrequencyBands_astro` is absent (and the reverse for a Single-Band product); order any product and assert `baselineReleaseSW_astro` never resolves to a legacy "YES"/"NO" value when a canonical alternative exists.
- **Verification:** re-run the exact live transcript from this session (order APX NEXT Enhanced, 4G LTE+5G, US) against the rebuilt container and confirm the payload matches the validated reference payload's shape (Msl present, Bands absent, carrierSelectionMultiSelect_astro present, wirelessCarrier_astro null, baselineReleaseSW_astro = "LATEST RELEASE").

### Not yet done / explicitly out of scope for this plan

- No code has been changed yet — this is a plan only, per this session's discipline of confirming root cause before implementing.
- The diagnosis step (item 2 above, checking whether Msl/carrierSelectionMultiSelect are filtered out of `attrs` entirely) was not performed this session and should be the first concrete action before writing any fix code — it determines whether this is an auto-fill ordering bug or an attribute-visibility bug, which would call for different fixes.
