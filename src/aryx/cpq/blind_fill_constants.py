"""Named allowlists of attrs individually verified safe to blind-fill
despite `_no_real_fill_justification` finding no rule coverage, split out
of `cpq/engine.py`'s module-level scope (Phase 4, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md -- module-level constant extraction, done
purely to shrink engine.py further). Re-exported from `aryx.cpq.engine`
(see the import there) so every existing `from aryx.cpq.engine import
<name>` caller/test keeps working unchanged. Logic unchanged from the
original inline definitions.
"""

from __future__ import annotations

# Explicit, named business-accepted exceptions to the dynamic check
# above -- NOT a technical classification, a deliberate product decision
# to trade guess-risk for fewer prompts on ONE specific attribute.
# accessoriesSolutionSet_astro (2026-08-16): its real constraint
# ("Constraint solution set based on product") depends on Oracle_
# BomItemMap/Oracle_BomItemDef, not yet ingested -- until they are, it
# blind-picks the first menu option instead of asking. No further change
# needed once ingestion lands: the confident branches this exception
# doesn't touch (recommendation match, Data Table single-match, exactly-
# one-remaining-option) all run BEFORE the blind-pick fallback, so a
# real constraint narrowing this to one legal category will auto-fill
# through one of those first and the blind guess simply stops firing.
#
# 2026-08-18: three siblings added, each individually confirmed via live
# rule-action data (not assumed from a shared code shape) to have the
# identical constraint-only governance profile as accessoriesSolutionSet_
# astro above -- a real rule (recommendation OR constraint) targets the
# attribute's own value, but _no_real_fill_justification's recommendation-
# only check can't see the constraint, so it was blocked from ever
# reaching the confident branches even though real catalog governance
# exists:
#   - relatedServicesType_astro ("Service Type"): real script-backed
#     constraint querying the real Data Table relSoftAndServcParts for
#     the current CPQ model (rule 18654807132, constraint_type=1).
#   - relatedServiceCategory_astro ("Service Category"): real constraint
#     (rule 17691443159, script-backed) plus a declarative one (rule
#     17691443165) -- hidden until relatedServicesType_astro resolves.
#   - selectEndUserType_astro ("Select End User Type"): one real
#     constraint (rule with attribute_id 17691442... verified via live
#     rule-action query), zero recommendations.
# A GENERIC fix (letting rule_governed_ids' hiding+recommendation+
# constraint union satisfy this check for every attr) was tried and
# reverted the same day -- it also let additionalSystemEnhancementFeature
# Type_astro (the documented "9-of-11, never guess" incident this whole
# check exists to prevent) bypass the gate, and separately let Group-1
# hiding-only-governed attrs (e.g. cBPQRCode_astro) skip their
# missing-data-table warn-and-skip. This named-allowlist approach only
# grants the exception to attributes individually verified safe.
_BLIND_FILL_RISK_ACCEPTED_VNS: frozenset[str] = frozenset({
    "accessoriesSolutionSet_astro",
    "relatedServicesType_astro",
    "relatedServiceCategory_astro",
    "selectEndUserType_astro",
    # 2026-08-19: four siblings added, each individually confirmed via the
    # real Attrsequence Data Table (per-base-model AttrName+CPQModel+
    # BaseModel+optionOrReqFlag rows, workspace 93) to be Required for
    # nearly every base model -- a real governance signal
    # _no_real_fill_justification can't see, since it only checks
    # ConfigAttr.required (sourced from bm_config_attr.required, confirmed
    # live to be 0/unreliable for essentially every attribute in this
    # catalog, not the real per-base-model flag) and rec_by_target. Each
    # was live-verified separately, not assumed from a shared shape:
    #   - baselineReleaseSW_astro ("Software Release"): 448/449
    #     Attrsequence rows marked Required.
    #   - applicationServicesSelection_astro ("Application Services
    #     Selection"): 28/28 rows marked Required (always).
    #   - carrierSelectionMultiSelect_astro ("Carrier Selection"): 3/3
    #     rows marked Required (always) -- also cited by name in this
    #     file's own auto_fill multi-select branch as governed via real
    #     attrSequence coverage.
    #   - wirelessCarrier_astro ("Wireless Carrier"): Required (flag "R")
    #     under real APX NEXT CPQModels (APXNEXTSINGLE, APXNEXTXNALL,
    #     APXNEXTINTLFED, APXNEXTINTL, ...) for 9 base models -- confirmed
    #     live to share ZERO base models with carrierSelectionMultiSelect_
    #     astro's own Required coverage (single base model H55TGT9PW8BN).
    #     The two are mutually-exclusive per-base-model siblings for the
    #     same real-world "carrier" concept (single-select on some base
    #     models, multi-select on others), not one legacy/one real -- both
    #     genuinely required, just never for the same base model.
    #   - packingPackageType_astro ("Package Type"): 452/453 Attrsequence
    #     rows marked Required. Distinct from its own real constraint
    #     rule (18131370895, script-backed on additionalSystemEnhancement
    #     FeatureType_astro/ICE KIT) which already auto-fills it when that
    #     rule resolves to exactly one legal value -- this allowlist entry
    #     only covers the fallback case where that constraint hasn't
    #     narrowed anything yet.
    # Two siblings from the same investigation were deliberately NOT
    # added: solutionTypeDuration_astro (6/215 Required -- mostly
    # optional, base-model dependent) and applicationServicesIntroBundle_
    # astro (12/86 Required -- same caveat). promoApplicationServices_
    # astro/additionalApplicationServices_astro/aTAKNonPromoApplication
    # Services_astro were also checked and confirmed genuinely optional
    # (0 Required rows each) -- correctly excluded, not an oversight.
    "baselineReleaseSW_astro",
    "applicationServicesSelection_astro",
    "carrierSelectionMultiSelect_astro",
    "packingPackageType_astro",
})

# Subset of _BLIND_FILL_RISK_ACCEPTED_VNS's 2026-08-19 additions that were
# individually confirmed Required (not just "safe to blind-fill via real
# governance rules", the reason the set's other four members are in it) —
# see that set's docstring for the per-attribute Attrsequence row counts.
# Used by `_is_mandatory_input_attr` for beautify's Mandatory/System split
# instead of the unreliable flat ConfigAttr.required/bm_config_attr.
# required column (same docstring, "confirmed live to be 0/unreliable for
# essentially every attribute in this catalog").
#
# packingPackageType_astro deliberately excluded (2026-08-19, rebase-time
# reconciliation with docs/CPQ_PackageType_HardExclude_RCA_2026-08-19.docx
# and docs/CPQ_Beautify_Mandatory_Section_Miscategorization_2026_08_19.md):
# a high Attrsequence Required row-count alone does NOT mean a real
# Mandatory-User-Input UI field -- Package Type is one of the confirmed
# exceptions (`_RECOMMENDED_CONFIG_ONLY_VNS` in engine.py), live-verified
# against the real native APX NEXT screenshot to appear ONLY under
# "Recommended Configuration," never under "Mandatory User Input,"
# regardless of its Attrsequence row count. Including it here would have
# unconditionally (no per-consumer gate) leaked it back into
# `config_data` too, directly contradicting that already-verified
# classification.
_ATTRSEQ_CONFIRMED_REQUIRED_VNS: frozenset[str] = frozenset({
    "baselineReleaseSW_astro",
    "applicationServicesSelection_astro",
    "carrierSelectionMultiSelect_astro",
    "wirelessCarrier_astro",
})
