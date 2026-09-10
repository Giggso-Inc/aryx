"""Coarsest-first rule ordering built on the condition-depth graph.

Phase 4 step 9 extraction from ``cpq/engine.py``. `_attribute_depth_
ranks` is reached off the passed-in `engine` (preserving the original
`self.` lookup, so subclass/instance/patched overrides still win).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.state import (
        ConfigAttr, ConstraintRule, HidingRule, RecommendationRule,
    )


def rank_rules_by_specificity(
    engine: Any,
    attrs: list["ConfigAttr"],
    hiding_rules: list["HidingRule"],
    rec_rules: list["RecommendationRule"],
    con_rules: list["ConstraintRule"],
    display_order: dict[str, int] | None = None,
) -> tuple[list["HidingRule"], list["RecommendationRule"], list["ConstraintRule"]]:
    """Stable-sort hiding/recommendation rules coarsest-condition-first,
    most-specific-condition-last, so the existing "last rule wins"
    semantics in apply_hiding_rules/apply_recommendation_rules resolve
    same-target conflicts via provable specificity instead of
    whatever order fetch_rules()/fetch_value_rules() happened to
    return (neither has an ORDER BY — confirmed in rdb.py). See
    docs/CPQ_RULE_SPECIFICITY_EXECUTION_ORDER_PLAN_2026_08_04.md.

    display_order — docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §2b:
    the catalog's FULL layout document order (`_load_layout_full_
    order` — includes layout-hidden attrs like a derived Base Model,
    unlike `load_layout_display_order`'s visible-only map, since a
    rule's condition attribute is very often itself hidden). When
    supplied, tier 2 below (a real declarative condition) ranks by the
    MAX layout position among the condition's attribute(s) instead of
    _attribute_depth_ranks' graph depth — confirmed live to matter:
    `hWVersion_astro` sits at a shallow depth in the dependency graph
    but gates real downstream decisions, while depth alone doesn't
    reflect the real native UI's own notion of "how far into the
    configuration flow" a condition sits. A condition attribute absent
    from the layout (shouldn't normally happen — every real condition
    attribute is a real catalog attribute — but the layout file may
    simply not mention it) ranks at position -1 within tier 2, i.e.
    least specific among real declarative conditions, never treated as
    equal-or-better than a measured position (this codebase's
    "unknown never outranks known" convention). `None` (the default)
    keeps today's depth-based ranking completely unchanged.

    con_rules is returned UNCHANGED — apply_constraint_rules' allowed-
    value intersection (_intersect) is commutative, so reordering it
    can never change its result; doing so would only reorder log
    lines/BML prefetch scheduling for zero correctness benefit.

    Three specificity TIERS, least to most specific (a rule's own
    `condition_script` — a separate gating script — is structural
    metadata we can see without parsing script CONTENT; the graph
    depth from _attribute_depth_ranks only ever comes from real
    declarative conditions, since that's the only thing it can
    extract edges from):

      0. No gating condition at all — no `conditions`, no
         `condition_attr_id`, no `condition_script` (whether or not
         it has a value-only `script`, e.g. a hiding/recommendation
         rule that just always returns one fixed outcome/value with
         no separate condition). Least specific — sorts first.
      1. Gated by a `condition_script` but no declarative condition
         info at all — a real, live example: workspace 39004's
         "Default to Latest Release if not NA/fed customer" is
         condition_script-gated with condition_attr_id=0/no
         conditions, competing against "Set default to Baseline
         Release" (tier 0, a bare value script, no condition_script)
         on the same target. We can't measure exactly how deep the
         condition_script's own logic sits, but its mere presence
         proves the rule is MORE narrowly scoped than an
         unconditional tier-0 rule, so it ranks after tier 0 and
         wins ties against it — without ever parsing what the
         script actually checks.
      2. A real declarative condition (`conditions`/
         `condition_attr_id`) — ranked by the MAX depth
         (_attribute_depth_ranks) among the attribute(s) it
         references. Most specific, provably ordered within this
         tier; always sorts after tiers 0 and 1.

    Within tiers 0/1 (where exact specificity isn't measurable),
    ties are broken by the rule's own target's ConfigAttr.order —
    never by "last unknown wins," matching apply_hiding_rules'/
    apply_recommendation_rules' own "unknown -> don't act/don't
    guess" convention for script outcomes elsewhere in this file.

    attrs MUST be the full, pre-loop catalog as passed into
    evaluate_rules_loop — never a loop-local `attrs` already shrunk
    by apply_hiding_rules, which would wrongly zero out predecessors
    for hidden attributes.
    """
    id_to_vn: dict[int, str] = {}
    for a in attrs:
        id_to_vn.setdefault(a.entity_id, a.variable_name)
    for a in attrs:
        if a.source_id is not None:
            id_to_vn[a.source_id] = a.variable_name
    order_by_vn = {a.variable_name: a.order for a in attrs}

    depth_by_vn = engine._attribute_depth_ranks(attrs, [*hiding_rules, *rec_rules])

    def _rule_rank(rule: Any) -> tuple[int, int, int]:
        cond_ids: list[int] = []
        conditions = getattr(rule, "conditions", None)
        if conditions:
            cond_ids = [cid for cid, *_rest in conditions]
        else:
            cid = getattr(rule, "condition_attr_id", 0)
            if cid:
                cond_ids = [cid]
        cond_vns = [
            id_to_vn[cid] for cid in cond_ids
            if cid in id_to_vn and id_to_vn[cid] in depth_by_vn
        ]
        if cond_vns:
            if display_order is not None:
                return (2, max(display_order.get(vn, -1) for vn in cond_vns), 0)
            return (2, max(depth_by_vn[vn] for vn in cond_vns), 0)

        target_id = getattr(rule, "target_attr_id", None)
        target_vn = id_to_vn.get(target_id) if target_id else None
        fallback_order = order_by_vn.get(target_vn, 10**9) if target_vn else 10**9
        if getattr(rule, "condition_script", None):
            return (1, 0, fallback_order)
        return (0, 0, fallback_order)

    sorted_hiding = sorted(hiding_rules, key=_rule_rank)
    sorted_rec = sorted(rec_rules, key=_rule_rank)
    return sorted_hiding, sorted_rec, con_rules
