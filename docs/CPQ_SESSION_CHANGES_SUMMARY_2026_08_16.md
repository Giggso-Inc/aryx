# CPQ Engine Fixes — Session Summary (2026-08-16)

**Branch:** `fix/quantity-dev-rv` (rebased onto `dev-rv`, pushed to `origin/fix/quantity-dev-rv`)
**Committed:** `02e76f0 fix(cpq): correct multi-select/blind-fill defaults and dormant-value handling`
**Pending (uncommitted at time of writing):** refinement to the blind-fill guard (see item 5)

## Problem Statement

Configuring APX NEXT (Enhanced / XE 4G LTE+5G) for USA through the chat-driven CPQ flow produced a `config_data` payload that diverged from the real native Oracle CPQ UI in several concrete ways: attributes the customer visibly answered (all 3 Frequency Band checkboxes) were silently truncated to one value; attributes the UI never asks about at all were still being asked; and other attributes were auto-filled with values that had zero basis in the ingested rule/data — all while adjacent bugs in the auto-fill pipeline caused genuinely-answered values to be dropped between conversational turns. This document tracks every root cause found and fixed, in the order they were diagnosed.

---

## 1. Orphaned duplicate Frequency Band attributes

**Symptom:** `modelSelectionFrequencyBands_astro` (20-option single-select) and `modelSelectionFrequencyBandPlus_astro` kept appearing in `config_data` for Enhanced/XE 4G LTE+5G, even though the real native UI only ever shows one "Frequency Band" control (`modelSelectionFrequencyBandMsl_astro`, 3-checkbox multi-select).

**Root cause:** both attributes have **zero `attrSequence` Data Table rows for any CPQModel, workspace-wide** — confirmed via direct Postgres query. `_suppress_ungoverned_attrs`'s existing "total silence, not confident exclusion" carve-out deliberately leaves attributes visible when there's no attrSequence data at all, on the theory that silence usually means missing tracking data, not confirmed exclusion. For these two specific attrs, cross-checked against real native-UI screenshots, the silence *is* confirmation — they're dead/legacy catalog leftovers.

**Fix:** `_CONFIRMED_DEAD_ATTRS` allowlist (`engine.py`), checked inside `_suppress_ungoverned_attrs` immediately before the "total silence" carve-out — forces suppression for these two specific attrs only, leaving the general carve-out untouched for every other attribute.

**Status:** ✅ Committed.

---

## 2. `auto_fill`'s resolved values silently discarded (7 call sites)

**Symptom:** Attributes the engine correctly auto-filled (e.g. `isProvisioningRequiredInCloudEnv_astro` → `YES`) never reached `session.filled` — they were correctly never re-asked, but their value vanished from the final payload.

**Root cause:** 7 call sites across `ask_api.py`'s cascade/turn handlers called `auto_fill(...)` as `_, _, pending = auto_fill(...)`, discarding its first two return values (the actually-resolved `filled`/`display_filled`). `auto_fill` builds its working copy via `dict(already_filled or {})` — a fresh copy, not an in-place mutation — so the discarded return was the *only* place the resolved values ever existed.

**Fix:** all 7 sites now capture `filled, display_filled, pending = auto_fill(...)` and use the real resolved values.

**Status:** ✅ Committed.

---

## 3. Dormant multi-select values wiped during a temporary hide window

**Symptom:** `modelSelectionFrequencyBandMsl_astro`'s auto-picked default got permanently lost between turns — filled correctly right after Hardware Version, gone by the time Product was answered on the next turn, even though the attribute becomes visible again once Product resolves.

**Root cause, two layers:**
- **`ask_api.py`:** `session.filled_multi` was rebuilt every turn as `{k: v for k, v in session.filled_multi.items() if any(a.variable_name == k for a in visible_attrs)}` — purging any attribute not visible in *that specific turn*, even if the only reason was a still-unanswered upstream decision field (Product/Base Model), not a real invalidation.
- **`engine.py` (`evaluate_rules_loop`):** the same over-eager purge existed one layer deeper — `for k in hidden_vns: filled.pop(k, None); ... multi.pop(k, None)` stripped values for *any* hidden attribute on *every pass*, regardless of why it was hidden.

**Fix:**
- `ask_api.py`: the filter now only drops a value when it's in `dropped_multi` (a real, cascade-confirmed invalidation) or no longer exists in the catalog at all — never merely "not visible this turn."
- `engine.py`: the strip is now conditional on all 4 decision anchors (`ultimateDestinationCountry`, `hWVersion_astro`, `productSelectionProduct_all`, `modelSelectionbaseModel_astro`) being answered. While any anchor is still blank, hidden attrs' values are preserved as dormant; once every anchor is answered, the original immediate-strip behavior is restored so genuine conflicts (e.g. Package Type vs. Product) still clear right away. An earlier, unconditional version of this fix caused a real regression (a Package Type ↔ Product re-ask loop) — this anchor-gated version was the corrected iteration.

**Status:** ✅ Committed.

---

## 4. Multi-select blind-pick kept only the first legal option, not all of them

**Symptom:** `modelSelectionFrequencyBandMsl_astro` only ever captured `["700/800 MHZ"]` in the payload, even when the real native UI showed all 3 boxes (700/800 MHz, VHF, UHF) checked.

**Root cause:** in `auto_fill`'s Data-Table-narrowed-legal-values branch, once the real Whitelist data confirmed the legal option set (3 rows: 700/800 MHZ, VHF, UHF), the code took only `_narrowed_opts[0]` — discarding the other 2 confirmed-legal values.

**Fix:** `_SELECT_ALL_NARROWED_LEGAL_MULTI_VNS` allowlist — for this specific attribute (whose real-world meaning is "which bands does this unit support," a coverage concept), all Data-Table-confirmed-legal options are selected, not just the first. Deliberately scoped narrowly: `carrierSelectionMultiSelect_astro` hits the same code path and needs the opposite behavior (native UI leaves it genuinely unresolved on a real tie), so this isn't a blanket change to the branch.

**Status:** ✅ Committed.

---

## 5. Blind-filling attributes with zero real justification

**Symptom:** `additionalSystemEnhancementFeatureType_astro` ("Disable Cloud Services") was silently pre-selected with no basis, which then cascaded into narrowing `additionalApplicationServices_astro`'s legal SmartX option set from 10 defaults down to 5 — forcing an unnecessary "no longer valid, please re-pick" re-ask. Auditing the full payload turned up 4 more attributes with the identical shape.

**Root cause:** these 5 attributes are all `required=False` with **no real `default_value`** and **zero recommendation rules** ever targeting them, yet `governed_target_ids`'s blanket "any `required=False` attr is blind-fill-eligible" widening (added earlier to keep the conversation to ≤3 prompts) swept them in anyway, letting them fall through to a first-by-order guess with nothing behind it.

**Fix (two iterations):**
- **First pass (committed):** excluded all 5 attrs from `governed_target_ids` entirely, plus added a direct `vn not in _NEVER_BLIND_FILL_VNS` guard on the one independent multi-select fallback branch that wasn't gated by `governed_ids` at all.
- **Refinement (pending, uncommitted):** the first pass was too broad — excluding from `governed_target_ids` also blocked these attrs' own *confident* auto-fill paths (e.g. a real constraint narrowing to exactly one legal option once `Oracle_BomItemMap`/`Oracle_BomItemDef` are ingested). Reverted the `governed_target_ids` exclusion; the guard now lives only at the specific auto_fill fallback sites that had no real-data check at all — the multi-select "nothing to justify a subset" fallback, and the two single-select first-by-order fallbacks (`display_order`-based and the final bare-menu-order case). Every more-specific, confident branch (satisfied recommendation, Data Table single match, confirmed-valid default under an active constraint, exactly-one-remaining-option) is untouched and fires normally whenever real data supports it.

**Status:** ⏳ First pass committed; refinement pending commit.

---

## Data gaps identified (not code bugs — separate workstream)

Cross-referencing all 754 rule scripts' `BMQL` table references against what's actually ingested in Postgres (workspace 43) surfaced two confirmed-missing tables:

| Table | Referenced by | Blocks |
|---|---|---|
| `Oracle_BomItemMap` + `Oracle_BomItemDef` | 5 rules, including `accessoriesSolutionSet_astro`'s "Solution Set" constraint | Real product-specific accessory category resolution |
| `UserGroupMapping` | 4 rules (already explicitly handled as a known-missing-table skip) | `dHSAssetTagLabel_astro`, `cBPQRCode_astro`, `fedQRCode_astro` |

All 3 corresponding CSVs (found locally, schema-verified against the BML scripts' expectations) were queued for ingestion via `/admin/ingest/file`. The first attempt was interrupted by a Docker Desktop engine crash; a second attempt was queued after recovery. Ingestion status was still in progress as of this document.

---

## Container state

Both `aryx_msi-api-1` (real image rebuild via `docker compose build`) and `aryx-fix-datatables-rv-api-1` (full `src/aryx` tree sync + restart, since its compose file is not present locally) were rebuilt and confirmed healthy after every fix in this document, including the pending refinement.

## Git state

- Commit `02e76f0` pushed to `origin/fix/quantity-dev-rv`, rebased onto latest `dev-rv` (7 commits pulled in, including a more complete 249-country alias-group implementation that superseded this branch's own earlier, narrower 2-country fix during conflict resolution).
- Item 5's refinement (governed_target_ids revert + two new single-select guards) is **not yet committed** — working tree currently holds this change uncommitted on top of `02e76f0`.
