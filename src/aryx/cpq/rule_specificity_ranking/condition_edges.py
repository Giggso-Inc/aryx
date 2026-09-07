"""Rule-condition dependency graph: raw edge extraction plus the
longest-path depth ranks derived from it (Phase 4 step 9 extraction from
``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`_attribute_depth_ranks` reaches `_rule_condition_edges` back through
``CpqEngine`` on the engine MODULE object rather than calling the local
function directly, so the original ``CpqEngine._rule_condition_edges``
lookup -- and therefore any test that patches that class attribute --
keeps working exactly as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aryx.cpq import engine as _engine_module

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.state import ConfigAttr


def _rule_condition_edges(
    attrs: list["ConfigAttr"],
    rules: list[Any],
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[int, str]]:
    """Shared, UNFILTERED rule-condition -> target edge extraction.

    Returns (predecessors, successors, id_to_vn):
      predecessors[target_vn] = set of condition_vn that gate it
      successors[condition_vn] = set of target_vn it gates
      id_to_vn = BM-native id -> variable_name (ConfigAttr.source_id
        preferred, falls back to entity_id — same dual-id convention
        _attr_index already uses)

    Edges come from every rule with a real DECLARATIVE condition
    (`conditions`, or a nonzero `condition_attr_id`) — one edge per
    distinct attr_id referenced. Unlike a payload-key-ordering
    consumer (_dependency_ordered_keys), this does NOT restrict edges
    to any subset of attrs/keys: a rule's condition attribute may be
    currently hidden or unfilled (and so absent from a given turn's
    output) while still being a real, structural gate that rule-
    specificity ranking (_attribute_depth_ranks) needs to see.
    """
    attr_by_vn = {a.variable_name: a for a in attrs}
    id_to_vn: dict[int, str] = {}
    for vn, a in attr_by_vn.items():
        id_to_vn.setdefault(a.entity_id, vn)
    for vn, a in attr_by_vn.items():
        if a.source_id is not None:
            id_to_vn[a.source_id] = vn

    predecessors: dict[str, set[str]] = {}

    def _add_edge(cond_id: int, target_id: int) -> None:
        cond_vn = id_to_vn.get(cond_id)
        target_vn = id_to_vn.get(target_id)
        if cond_vn and target_vn and cond_vn != target_vn:
            predecessors.setdefault(target_vn, set()).add(cond_vn)

    for r in rules:
        target_id = getattr(r, "target_attr_id", None)
        if not target_id:
            continue
        conditions = getattr(r, "conditions", None)
        if conditions:
            for cond_id, *_rest in conditions:
                _add_edge(cond_id, target_id)
        else:
            cond_id = getattr(r, "condition_attr_id", 0)
            if cond_id:
                _add_edge(cond_id, target_id)

    successors: dict[str, set[str]] = {}
    for target_vn, conds in predecessors.items():
        for c in conds:
            successors.setdefault(c, set()).add(target_vn)

    return predecessors, successors, id_to_vn


def _attribute_depth_ranks(
    attrs: list["ConfigAttr"],
    rules: list[Any],
) -> dict[str, int]:
    """Longest-path-from-root depth per variable_name in the rule
    condition-gating graph (see _rule_condition_edges) — a generic,
    catalog-agnostic stand-in for "how broad vs. specific is this
    attribute" (docs/CPQ_RULE_SPECIFICITY_EXECUTION_ORDER_PLAN_
    2026_08_04.md): depth 0 = nothing gates this attribute (coarsest
    anchor); each attribute's depth = 1 + the max depth of whatever
    gates it (e.g. the confirmed Hardware Version -> Product
    Selection constraint means Product Selection's depth is Hardware
    Version's depth + 1).

    Cycle-safe: a genuine cycle (or anything transitively downstream
    of one) never reaches zero remaining in-degree during the
    Kahn's-algorithm peel below. Those nodes get max(all resolved
    depths) + 1 rather than depth 0 — an unverifiable/cyclic
    dependency must never be treated as "most trusted," which depth
    0 would imply.
    """
    predecessors, successors, _id_to_vn = (
        _engine_module.CpqEngine._rule_condition_edges(attrs, rules)
    )
    all_vns = {a.variable_name for a in attrs}

    remaining = {vn: len(predecessors.get(vn, ())) for vn in all_vns}
    depth: dict[str, int] = {}
    ready = [vn for vn, n in remaining.items() if n == 0]
    for vn in ready:
        depth[vn] = 0
    visited: set[str] = set(ready)

    while ready:
        vn = ready.pop(0)
        for succ in successors.get(vn, ()):
            if succ not in all_vns:
                continue
            depth[succ] = max(depth.get(succ, 0), depth[vn] + 1)
            remaining[succ] -= 1
            if remaining[succ] == 0 and succ not in visited:
                visited.add(succ)
                ready.append(succ)

    resolved_depths = list(depth.values())
    fallback_depth = (max(resolved_depths) + 1) if resolved_depths else 0
    for vn in all_vns:
        if vn not in depth:
            depth[vn] = fallback_depth
    return depth
