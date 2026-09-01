# Bug Report: Live-session payload disagrees with rendered UI (Carrier + Frequency Band), plus a blocking internal constraint error

**Date:** 2026-08-07
**Product:** APX NEXT Single Band, Hardware Version "APX NEXT (4G LTE Only)", Base Model `H45TGU9PW8AN`
**Destination:** United States
**Source:** Real Oracle CPQ session screenshot (Model Configuration page) + the session's own captured `configData` payload, supplied by the user in the same turn.
**Scope note:** this is a live Oracle CPQ instance issue, observed directly — not an Aryx ingestion or code artifact. No Aryx code is implicated by this report.

---

## 1. Problem

Three fields the UI renders as user-selected do not match the corresponding fields in the session's own `configData` payload, and the page is currently carrying a blocking constraint error.

## 2. Evidence (field-by-field)

| Field | UI shows | Payload shows | Match? |
|---|---|---|---|
| Wireless Carrier | **ATT/FirstNet** (dropdown) | `wirelessCarrier_astro = "LTE CAPABILITY NO SERVICE"` | **No** |
| Frequency Band | **VHF** (radio button, clearly selected) | `modelSelectionFrequencyBands_astro = "700/800 MHZ"`<br>`modelSelectionFrequencyBandMsl_astro.items = [{"value":"700/800 MHZ"}]`<br>`modelSelectionPrimaryFrequency_astro = "7/800 MHZ"`<br>`modelSelectionSecondaryFrequency_astro = "7/800 MHZ"` | **No** — all 4 related fields say 700/800 MHz, none say VHF |
| Carrier (sibling pair) | n/a (single carrier control shown) | `carrierSelectionMultiSelect_astro.items = [{"value":"ATT/FIRSTNET"}]` **and** `wirelessCarrier_astro = "LTE CAPABILITY NO SERVICE"` — both populated, different values | **Conflict** |
| Page-level | Banner: *"1 WARNINGS — Internal constraint error. Constraint defined on following hidden attribute(s): Sales Approver Email Address"* | n/a | Blocking |

## 3. Root cause — as far as evidence allows

- **Sibling double-fill (confirmed pattern):** `carrierSelectionMultiSelect_astro` and `wirelessCarrier_astro` are documented mutually-exclusive siblings (one hides when the other applies, per the catalog's own hiding rules). Here **both are populated with different carrier values** — the same conflict pattern this investigation traced to the empty `hiddenConstraintMasterString_astro`/`hiddenMasterStringForAstroPortable_astro` master strings in every static export. This is the first time it's been observed directly in a **live** session rather than inferred from a static export.
- **Wireless Carrier mismatch:** `LTE CAPABILITY NO SERVICE` is normally forced only by the FEDERAL+ATAK or "Delete LTE" branches (see `docs/CPQ_CARRIER_WIRELESS_FREQBAND_DATA_GAP_PROOF_2026_08_07.md` §2.3) — but this payload's own `aTAKEnabledPackage_astro="NO"` rules that branch out. The literal documented override rule does not explain this value; the mechanism producing it in this specific session is not determinable from a payload + screenshot alone.
- **Frequency Band mismatch:** no override/force rule for this attribute is documented anywhere in the rule inventory (§3 of the same proof doc) — nothing in the known rule set would justify 700/800 MHz appearing when VHF is the rendered selection. Most consistent explanation: a **stale/out-of-sync capture** — the payload reflects an earlier resolved state than what the user most recently selected on screen.
- **Sales Approver Email Address constraint error:** unrelated to the two mismatches above — a separate, active block on this transaction, most likely an approval-routing/discount-threshold rule tied to a hidden attribute not visible in this payload.

**Honest limit:** pinning the exact mechanism for #1 and #2 (which rule fired, in what order, relative to the user's UI edit) requires the live session's rule execution trace/log from the Oracle CPQ instance itself — not reconstructable from a payload and a screenshot.

## 4. Open question for whoever owns this Oracle CPQ instance

1. Pull the rule-execution trace for this exact session/transaction — confirm which rule last wrote `wirelessCarrier_astro` and each of the 4 frequency-band fields, and at what timestamp relative to the user's VHF/ATT-FirstNet selections.
2. Confirm whether `configData` exports (like the one captured here) are guaranteed to reflect the *current* UI state, or can lag behind un-saved/un-submitted UI edits — this alone could fully explain both mismatches without any rule bug at all.
3. Resolve the "Sales Approver Email Address" hidden-attribute constraint blocking this transaction before anything else is investigated — the quote cannot be finalized while it's active regardless of the carrier/band question.

## 5. Why this matters

This is the first **live** (not static-export-inferred) confirmation of the sibling-conflict pattern this whole investigation has documented — evidence that the underlying data gap has real, user-visible consequences in production, not just a theoretical risk in Aryx's ingestion path.
