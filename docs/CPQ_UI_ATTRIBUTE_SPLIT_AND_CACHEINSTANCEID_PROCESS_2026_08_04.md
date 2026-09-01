# CPQ UI Attribute Split & cacheInstanceId Process — Confirmed Root Cause

Session date: 2026-08-04 · Source: `Quoting by NLP - CPQ APIs (1).xlsx` (real, captured Oracle CPQ REST call samples) cross-referenced against this session's live Aryx testing and raw catalog XML analysis.

---

## Problem statement

Throughout this session, comparisons between a small (~8-field) "reference/correct" payload and Aryx's full (~80-90 field) generated payload were treated as an open question: were these two genuinely comparable, or structurally different calls being compared? This document resolves that question **definitively**, using real captured API request/response samples from `Quoting by NLP - CPQ APIs (1).xlsx` — not inference.

## Confirmed: the real Oracle CPQ REST flow splits configuration across TWO distinct API calls, not one

The xlsx's "APIs" sheet documents the full transaction sequence with real sample payloads:

| Step | API | Purpose (per the sheet's own "Outcome" column) |
|---|---|---|
| 1 | `_new_transaction` | Creates the quote; returns `bs_id` |
| 2 | `changeCustomer_t` | Attaches the customer |
| 3 | `cleanSave_t` | Checkpoint save |
| 4 | **`_configure`** | Starts a configuration session. `cacheInstanceId: "-1"` signals "no session yet." **Sends only a SMALL, curated configData** (in the sheet's own sample: `hWVersion_astro`, `productSelectionProduct_all`, `modelSelectionFrequencyBandMsl_astro`, `baselineReleaseSW_astro`, `isProvisioningRequiredInCloudEnv_astro`, `wirelessCarrier_astro=null`, `carrierSelectionMultiSelect_astro`). Outcome: *"Collect cacheInstanceId required for further API request."* |
| 5 | **`_interact`** | Called with the now-populated `cacheInstanceId`. Outcome, quoted verbatim from the sheet: **"Call the interact API with configData for the attributes where the values are not been sent in `_configure`."** This is the explicit, documented mechanism for sending the REST of the configuration. |
| 6 | `_update` | `cacheInstanceId` only, no `configData` — a refresh/ack call. |
| 7 | `_addToTxn` | `cacheInstanceId` only — finalizes the configuration onto the transaction. |
| 8 | `cleanSave_t` | Final save; then line-item quantities are set via a separate `cleanSave_t` call. |

**This single line — "call `_interact` with configData for the attributes where the values are not been sent in `_configure`" — is the confirmed, documented resolution to the "8 vs 83 attributes" question raised throughout this session.** The real system was never expected to receive everything in one call. It is architected as exactly two configData-bearing calls: a small `_configure` payload, then one or more `_interact` calls carrying everything else.

## Second confirming example: the SVX Video Remote Speaker sample

The xlsx's "SVX Video Remote Speaker" sheet shows a real, more elaborate case with the SAME two-call split, plus an explicit flag confirming the mechanism:

- `_configure`'s `configData` carries a first set of attributes (`ultimateDestinationCountry`, `archeType_viSoln`, `dMSDuration_viSoln`, `modelSelectionSelectModel_viSoln`, `refresh_viSoln`, an array-set for mounting quantity).
- `_interact`'s request body explicitly includes **`"delta": true`** alongside its own `configData` — confirming, at the field level, that this second call's payload is understood by the system as an incremental delta on top of `_configure`'s state, not a replacement or a duplicate.

## What this means for Aryx's current behavior

Aryx's `build_payload()` currently emits **one single, complete configData snapshot** (~80-90 attributes for a typical APX NEXT order) at `confirm` time, with no concept of a two-call split or a `cacheInstanceId` session at all. This was investigated and confirmed genuine this session:

- All ~80-90 attributes Aryx emits are legitimate, real, transaction-eligible catalog data (verified directly against the raw XML: none carry `hidden=1`, `hide_in_trans=1`, or `set_type=2` — the flags that would mark them as internal noise). Aryx is not shipping garbage.
- The catalog's own layout/UI-placement data (checked via both the ingested database and the raw XML export) does **not** contain a native-UI "one screen's worth of fields" grouping finer than a ~35-attribute section — so Aryx's engine has no data-driven way to know, on its own, which attributes belong in an initial `_configure` call versus a follow-up `_interact` delta call.
- The `_configure`-vs-`_interact` split is a property of **the downstream integration layer** (whatever system takes Aryx's `cpq_payload` and drives the actual Oracle CPQ REST sequence) — not something Aryx's conversational engine currently has a mechanism for, and not something derivable purely from the catalog data ingested so far.

## Recommendation

1. **Do not attempt to shrink Aryx's `build_payload()` output to ~8 fields.** That would under-serve the `_interact` step, which is explicitly designed to receive "the attributes where the values are not been sent in `_configure`" — i.e., the bulk of a real configuration is *supposed* to travel through `_interact`, not be discarded.
2. **The real fix belongs in the integration layer**, not in Aryx's engine: whatever component calls Oracle CPQ's REST API needs to split Aryx's full `cpq_payload` into (a) a small `_configure` call carrying the core identity/decision attributes (Hardware Version, Product, the primary Frequency Band/Carrier selections, Software Release, Cloud Provisioning) and (b) one or more subsequent `_interact` calls (with `"delta": true`) carrying the remaining auto-configured attributes.
3. **A precise, catalog-verified list of which attributes belong in the "core `_configure`" bucket** is available from this session's live testing — see the confirmed reference sample in this same xlsx (`hWVersion_astro`, `productSelectionProduct_all`, `modelSelectionFrequencyBandMsl_astro`, `baselineReleaseSW_astro`, `isProvisioningRequiredInCloudEnv_astro`, `wirelessCarrier_astro`, `carrierSelectionMultiSelect_astro`, plus `ultimateDestinationCountry`) — this matches, field-for-field, the "reference payload" discussed throughout this session's earlier investigation.
4. If Aryx itself (rather than a separate integration layer) is expected to own this split going forward, that is a new feature — a `cacheInstanceId`-aware, two-phase submission flow — not a bug fix, and should be scoped and approved as its own piece of work.

## Not yet done / out of scope for this document

- No code changes were made based on this finding — this is a documentation/root-cause deliverable only, per the session's discipline of confirming root cause before implementing.
- Live re-verification of Aryx's current full payload for the exact ENHANCED order used as the running example throughout this session was in progress when this document was written; not included here.
