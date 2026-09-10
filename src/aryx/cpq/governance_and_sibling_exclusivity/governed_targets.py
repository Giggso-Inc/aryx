"""``governed_target_ids`` -- the wider Phase N default-or-first auto-fill
eligibility set (Phase 4 step 7 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

``_DECISION_REQUIRED_KEYS`` and ``CpqEngine`` are both reached through
the engine MODULE object rather than imported by name, so a patched
module-level constant or class method is still honored here.
"""

from __future__ import annotations

from aryx.cpq import engine as _engine_module
from aryx.cpq.state import (
    ConfigAttr, ConstraintRule, HidingRule, RecommendationRule,
)


def governed_target_ids(
    attrs: list[ConfigAttr],
    hiding_rules: list[HidingRule],
    rec_rules: list[RecommendationRule],
    con_rules: list[ConstraintRule],
) -> set[int]:
    """Entity ids eligible for default-or-first auto-fill.

    Widened per CPQ_APX_NEXT_ISSUES_PLAN.md Phase N: rule coverage alone
    left ~29 attrs pending on a richer catalog (APX Next) where most
    attrs simply carry no rule at all in the source data -- far short of
    the client's <=2-3-prompt requirement. Attrs marked `required=False`
    in the source are also eligible (a source-asserted "safe to default"
    signal), excluding decision-required attrs (country/region), which
    always ask regardless of governance. See `rule_governed_ids` for the
    strict rule-only subset (used to tag `filled_source`).
    """
    governed = set(
        _engine_module.CpqEngine.rule_governed_ids(
            attrs, hiding_rules, rec_rules, con_rules
        )
    )
    for attr in attrs:
        if attr.required:
            continue
        vn_flat = attr.variable_name.lower().replace("_", "")
        if any(dk in vn_flat for dk in _engine_module._DECISION_REQUIRED_KEYS):
            continue
        governed.add(attr.entity_id)
    # docs/CPQ_MULTISELECT_BLIND_PICK_RESPECTS_WHITELIST_PLAN_2026_08_
    # 10.md follow-up (2026-08-16, refined same day): attrs with no
    # real fill justification are DELIBERATELY left in `governed`
    # here -- an earlier version of this method unconditionally
    # excluded them by name, which also blocked their own confident
    # "a real constraint narrowed this to exactly one legal value"
    # auto-fill path (e.g. once Oracle_BomItemMap/Oracle_BomItemDef
    # are ingested, accessoriesSolutionSet_astro's constraint could
    # legitimately resolve to a single real category). The actual
    # "nothing justifies a guess" case is checked dynamically instead
    # at its specific, narrower call sites (auto_fill's unconditional
    # multi-select and single-select first-by-order fallbacks) -- see
    # `_no_real_fill_justification`'s own docstring for exactly which
    # sites and why each needed its own guard rather than one here.
    return governed
