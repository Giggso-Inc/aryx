"""``resolve_ui_layout_scope`` -- which attributes the real native UI shows,
and in what order (Phase 4 step 5 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Calls back onto ``CpqEngine._detect_layout_tier`` /
``_find_country_anchor_attr_id`` (both of which several tests replace on the
instance), so it takes an explicit ``engine`` first parameter and goes
through it rather than importing the extracted functions directly.
``get_cpq_rdb`` and ``_LAYOUT_SCOPE_CACHE`` go through the engine module
object -- both are patched/reassigned by dotted path in tests.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq import engine as _engine_module


def resolve_ui_layout_scope(
    engine, workspace_id: int, catalog_prefix: str = "",
) -> dict[str, Any] | None:
    """docs/CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md §1-§5 — which attributes
    the real native UI shows on screen, and in what order.

    Returns None for tier 3 (no layout data — caller keeps today's
    existing behavior unchanged, zero new code needed).

    Otherwise returns {"tier": 1|2, "flows": {flow_id: entry, ...}}.
    flow_id is 0 for tier 2 (no flow-rule scoping, one catalog-wide
    entry). Each entry is {"all": {attr_id: order_number},
    "section": {attr_id: order_number} | None} — "all" is every attr
    with layout placement (grouped/ordered, §4); "section" is the
    country-anchor's own parent_id group (§5) when exactly one such
    group exists for that flow, else None.

    Multiple rule_type=6 flows in one catalog (confirmed live: APX
    Next has 3) are a genuine, unresolved ambiguity — every
    disambiguation heuristic tried (biggest total flow, biggest
    immediate group) picked a DIFFERENT, WRONG flow when checked
    against the real ground-truth screenshot. This method deliberately
    does not guess: it returns one entry per flow and leaves picking
    one to the caller (e.g. a future curated per-catalog choice),
    rather than silently resolving to an unverified answer.
    """
    cache = _engine_module._LAYOUT_SCOPE_CACHE
    key = (workspace_id, catalog_prefix)
    if key in cache:
        return cache[key]
    tier = engine._detect_layout_tier(workspace_id, catalog_prefix)
    if tier == 3:
        cache[key] = None
        return None
    rdb = _engine_module.get_cpq_rdb()
    assoc = rdb.fetch_layout_attr_assoc(workspace_id, catalog_prefix)
    nodes = rdb.fetch_layout_model_nodes(workspace_id, catalog_prefix)
    country_attr_id = engine._find_country_anchor_attr_id(workspace_id, catalog_prefix)

    if tier == 1:
        flow_ids = {
            src_id for _eid, src_id, _name, _fn
            in rdb.fetch_rules(workspace_id, "6", catalog_prefix, active_only=True)
            if src_id is not None
        }
        by_flow: dict[int, list[tuple[int, int]]] = {}
        for rid, attr_id, lmid in assoc:
            if rid not in flow_ids:
                continue
            by_flow.setdefault(rid, []).append((attr_id, lmid))
    else:
        by_flow = {0: [(attr_id, lmid) for _rid, attr_id, lmid in assoc]}

    flows: dict[int, dict[str, Any]] = {}
    for flow_id, attr_lmids in by_flow.items():
        attr_group: dict[int, tuple[int, int]] = {}
        for attr_id, lmid in attr_lmids:
            node = nodes.get(lmid)
            if node is None:
                continue
            parent_id, _label, order_number = node
            if attr_id not in attr_group:
                attr_group[attr_id] = (parent_id, order_number)
        all_attrs = {aid: order for aid, (_p, order) in attr_group.items()}
        section: dict[int, int] | None = None
        if country_attr_id is not None and country_attr_id in attr_group:
            target_parent, _own_order = attr_group[country_attr_id]
            section = {
                aid: order for aid, (parent_id, order) in attr_group.items()
                if parent_id == target_parent
            }
        flows[flow_id] = {"all": all_attrs, "section": section}

    result = {"tier": tier, "flows": flows}
    cache[key] = result
    return result
