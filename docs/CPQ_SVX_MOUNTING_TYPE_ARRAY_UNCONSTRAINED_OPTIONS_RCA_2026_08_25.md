# CPQ — SVX Mounting Type (Array) Shows Unconstrained Option List — RCA

**Date:** 2026-08-25
**Status:** Analysis only — no code changed
**Reporter finding:** live side-by-side comparison of the real Motorola CPQ (Oracle native) UI vs. Aryx's conversational flow for the same quote (SVX Video Remote Speaker Microphone, US, Select Model = SVX Video Remote Speaker Mic TAA)

---

## Problem Statement

For the same quote context, the native Oracle CPQ UI's "Mounting Type" table shows exactly **6** valid mounting options:

1. Shirt Magnetic Mount
2. Jacket Magnetic Mount
3. Shirt Clip Mount
4. Jacket Clip Mount
5. Locking Molle Mount
6. TEK-LOK Belt Mount

Aryx's conversational flow, for the identical model/context, presents **12** options for `mountingTypeArray_viSoln` ("Mounting Type (Array)"):

1. Shirt Magnetic Mount
2. Jacket Magnetic Mount
3. Shirt Clip Mount
4. Jacket Clip Mount
5. Locking Molle Mount
6. Magnetic Mount
7. MOLLE Mount
8. Double Molle Mounts
9. KF Magnetic Mounts
10. KF Molle Mounts
11. TEK-LOK Belt Mount
12. Belt Mount

The extra 6 (Magnetic Mount, MOLLE Mount, Double Molle Mounts, KF Magnetic Mounts, KF Molle Mounts, Belt Mount) are real catalog options for `mountingTypeArray_viSoln` in general, but are **not valid for this specific model/context** — the native UI never offers them here, yet Aryx does.

---

## Root Cause

Aryx already has a constraint mechanism (`constrained_opts`) that narrows an attribute's raw catalog `options` down to the subset valid for the current context. This session's own test suite confirms it works correctly for **auto-fill**:

- `test_multiselect_with_several_constrained_options_and_no_default_defaults_to_empty` — `additionalSystemEnhancementFeatureType_astro` narrowed from 11 real options to 9 via `constrained_opts` before `auto_fill` decides anything.
- A live constraint rule (`"Constrain certain values for VX650"`, `type=constraint`) was observed firing during this session's own live verification run against real workspace data — confirming the underlying constraint-rule machinery is real, loaded, and active for this exact SVX/VX650 catalog.

However, **the code path that renders the numbered question list shown to the customer** (the "choose one: 1. ... 12. ..." prompt) enumerates `attr.options` directly. It does not appear to intersect that list against `constrained_opts.get(attr.entity_id)` the way `auto_fill` already does.

Result: the constraint is computed and respected when the engine silently *fills* a value, but is never consulted when the engine *asks* the customer to choose — so the customer sees the full, unconstrained 12-option raw catalog instead of the same 6-option set the native UI already filtered down to.

## Why This Happens (mechanism)

Two independent code paths read the same `ConfigAttr.options`:

| Path | Consults `constrained_opts`? | Evidence |
|---|---|---|
| `auto_fill` (silent fill / blind-pick / default resolution) | Yes | `test_cpq_multiselect_autofill_overselection.py` |
| Question-prompt rendering (numbered choice list shown to customer) | **No** (apparent gap) | This transcript — 12 shown vs. 6 real |

These two paths were built at different times for different purposes (one for unattended fills, one for interactive prompts) and were never unified to share the same constrained view of an attribute's valid options.

## Proposed Fix (not implemented)

When building the customer-facing numbered option list for any attribute, intersect `attr.options` with `constrained_opts.get(attr.entity_id)` when present — the same narrowing `auto_fill` already performs — so the customer is only ever offered the same context-valid subset the native UI shows.

**Before implementing, verify:**
- `constrained_opts` is actually populated for `mountingTypeArray_viSoln` **at the point the question is asked** (not only later, at auto-fill/validation time) — if the constraint's condition attribute isn't filled yet when this question is reached, the fix also needs a sequencing check, not just the intersection.
- No other catalog relies on seeing the full raw option list at question time (e.g. a catalog with no constraint rule for that attribute should be unaffected — `constrained_opts.get(id)` returning `None`/absent should mean "show all", preserving current behavior everywhere else).

## Risk

Low blast radius if scoped correctly (additive filter, only applies when a constraint is actually loaded for that attribute) — but must be verified against a catalog that currently depends on the full list being shown before this is turned on broadly.
