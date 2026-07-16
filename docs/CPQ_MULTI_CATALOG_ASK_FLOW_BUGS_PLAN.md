# CPQ Ask-Flow Bugs — Multi-Catalog Workspace (3 XML files ingested)

**Status: Bugs 1, 2, 3, 3c implemented and verified end-to-end** against the
live restarted service (`engine.py`: menu-option dedup, noise-var auto-default
in `auto_fill`, `productSelectionProduct_all` promoted to decision-required).
Re-running the exact "Quote APX Next radios for a US customer." transcript
confirmed: no duplicate Currency/Language/Number-Format questions,
`productSelectionProduct_all` resolves to `"APX NEXT ENHANCED"` (was
`"APX6500"`), neither noise var nor the product field's stale state reach the
final payload. Full suite: 34 passed, 3 pre-existing unrelated failures
(`detect_product_mention`/`run_id` logging — origin-merge regressions, not
touched), 6 skipped.

Separate from `docs/CPQ_RULE_TOOL_FLOW_PLAN.md` (rule extraction/evaluation,
already implemented) and `docs/CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md` (native-UI
attribute visibility). This plan covers bugs found in a REAL, live
conversation against the running service, with all three ingested catalogs
(APX Next, SVX Video RSM, SL3500e) sharing one workspace.

## Source conversation (verbatim, real system)

Question: *"Quote APX Next radios for a US customer."* — the live flow then
asked "User Currency" (options: 1. US Dollar, 2. US Dollar — duplicate),
"User Language" (1. English, 2. English — duplicate), "User Number Format"
(4 options, really 2 distinct values duplicated), before completing for
`aPXNext_BOM` and producing a payload with `productSelectionProduct_all:
"APX6500"` alongside unmistakably APX NEXT fields (`hWVersion_astro`,
`antennasType_astro="WHIP APX NEXT"`, etc.).

## Bug 1 — Duplicate options for company-level (global) attributes

**Confirmed root cause**: `_BM_USER_CURRENCY`, `_BM_USER_LANGUAGE`,
`_BM_USER_NUMBER_FORMAT` share the IDENTICAL native BigMachines id across
ALL THREE ingested files (`4119205`, `4121699`, `4121703` respectively) —
these are company/tenant-level attributes, not product-specific ones, so
every product export from the same BM tenant re-exports them verbatim.

`catalog_prefix` scoping (already proven correct elsewhere this session —
e.g. `aPXNext_BOM` resolved uniquely and correctly for the product itself)
namespaces each attribute's OWN entity type correctly (e.g.
`ApxNextConfigBmConfigAttr` vs the other catalogs' equivalents). But the
attribute→menu-item relationship the graph builds for these SPECIFIC
attributes appears to key off the raw native `ref_id`, which collides
across catalogs for shared/global fields — so `reader.neighbors()` returns
menu-item nodes from every ingested catalog that re-exports this same
global attribute, not just the one the current session is scoped to.

**Proposed fix**: when building attr→menu-item relationships at ingestion
(or when reading neighbors at query time), scope the match to the SAME
`catalog_prefix` as the attribute itself — same principle `_scope_to_catalog`
already applies to rule/attr entity types, extended to cover the
relationship edges these specific global attributes produce. Alternatively
(smaller blast radius): deduplicate menu options by `(item_value,
display_name)` before presenting them to the user — a real product-specific
attribute should never need this, but it's a safe backstop for the global
attrs this bug is specific to.

## Bug 2 — Global system attributes get ASKED at all

`_is_noise_var()` (`engine.py`, used inside `build_payload`) already
correctly identifies underscore-prefixed vars as system/integration noise
and excludes them from the final JSON payload — confirmed: none of
`_BM_USER_CURRENCY`/`_BM_USER_LANGUAGE`/`_BM_USER_NUMBER_FORMAT` appear in
the payload shown. But that filter runs ONLY at payload-build time. The
SAME fields still reach `auto_fill`'s pending-question path and get asked
in conversation — an inconsistent application of a rule already proven
correct for one purpose but not reused for the other.

**Proposed fix**: apply `_is_noise_var()` (or an equivalent check) as an
exclusion filter in `auto_fill`'s pending-attribute selection too — same
one-line structural check, reused instead of duplicated, so noise vars are
never asked, matching how they're never included in the final payload.
Low risk: these fields already have real default values in the XML
(confirmed: `_BM_USER_CURRENCY` etc. resolve to `USD`/`English`/`####,##`
range defaults) — excluding them from `pending` doesn't lose any real
customer-facing decision, it just stops asking a question whose answer was
never going to reach the payload anyway.

## Bug 3b — Cross-catalog attribute bleed into the same payload (new, confirmed from this transcript)

The full JSON payload in this transcript contains `videoRSM_astro` ("SVX Video RSM with Magnetic Shirt Mount"), `serviceTypeRSM_astro`, `rSMDMSDuration_astro`, and `videoRSMDeviceManagementDuration_astro` — these are body-camera/video-RSM accessory attributes that legitimately co-exist WITH an APX Next radio order (a video remote speaker mic is a real accessory sold alongside APX Next radios, per the response's own summary: "a video remote speaker mic"), so this specific set is plausibly correct cross-sell content, not contamination — but it is the same class of attribute-name collision risk as Bug 1: if `videoRSM_astro`'s own native id or menu items collide with `SVX Video RSM.xml`'s own top-level camera attributes (`modelSelectionSelectModel_viSoln`, etc.), the SAME neighbor-merge risk described in Bug 1 applies here too, just not yet visibly triggered in this transcript. Recommend the Bug 1 fix (catalog-scoped relationship edges) be verified against `videoRSM_astro` specifically before considering Bug 1 closed, since it's the one non-global attribute in this payload most likely to alias with the SVX catalog by name/id.

## Bug 3 — `productSelectionProduct_all` picks the wrong product family (reconfirmed live)

Already documented as the open finding behind item 12 in
`CPQ_RULE_TOOL_FLOW_PLAN.md` and the layout-visibility session's payload
audit — this live run reconfirms it under real conditions, not simulation.
Root cause and fix already written up there: `productSelectionProduct_all`
is a shared, catalog-wide 325-option list (APX 6500, APX 5500, VX/DP/DM
series, APX NEXT variants all together); blind "first eligible option by
order" auto-fill lands on order=1 ("APX6500") whenever no explicit NL hint
or rule determines this specific attribute's value, even when every OTHER
field in the same payload is correctly APX-NEXT-specific. Proposed fix
(already scoped): treat `productSelectionProduct_all` as decision-required
(same tier as `country`/`region`) rather than eligible for blind
first-by-order fallback, OR derive it FROM the already-resolved catalog
(`aPXNext_BOM`) via the real "Set Base Model"-style rules instead of
independent auto-fill.

## Bug 3c — "re-evaluating" cascade message is cosmetic for `productSelectionProduct_all` (new, confirmed)

A follow-up turn in the same session changed Hardware Version to "APX NEXT
(4G LTE+5G)". The engine responded: *"Updated Hardware Version → APX NEXT
(4G LTE+5G). This invalidated: Product — re-evaluating."* — but the
resulting payload still carries `productSelectionProduct_all: "APX6500"`,
identical to the pre-change value. The cascade log claims this attribute
was invalidated and re-evaluated, but its value never actually changed.

This confirms Bug 3's fix can't be "let auto_fill re-run on cascade" alone
— `productSelectionProduct_all` isn't wired to any rule/cascade that reacts
to Hardware Version at all; the "invalidated: Product — re-evaluating"
message is generated by the generic cascade-invalidation path but the
attribute has no real recommendation/constraint rule driving it, so
re-evaluation silently falls back to the same blind first-by-order pick
every time. Fix must ensure `productSelectionProduct_all` is either (a)
actually driven by the real "Set Base Model"/product rules so a genuine
cascade recomputes it, or (b) excluded from the cascade-invalidation
message entirely if no rule governs it — showing "re-evaluating" for a
field that structurally cannot re-evaluate is misleading regardless of the
value-correctness bug itself.

## Net priority

Bug 1 and 2 are new, multi-catalog-specific, and are the direct cause of
the confusing duplicate-option UX in this transcript. Bug 3 is already
tracked elsewhere and reconfirmed here as evidence it's a live, not
theoretical, defect. Recommend bug 2 first (smallest, safest — reuse an
existing filter in a second place) before bug 1 (needs a decision on
ingestion-time vs query-time relationship scoping).
