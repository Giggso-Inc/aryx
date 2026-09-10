"""Payload-key topological ordering by rule-proven dependency.

Phase 4 step 9 extraction from ``cpq/engine.py``. Edge extraction is
reached back through ``CpqEngine`` on the engine MODULE object rather
than by calling the local `_rule_condition_edges` directly, preserving
the original ``CpqEngine._rule_condition_edges`` lookup (and therefore
any test that patches that class attribute).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aryx.cpq import engine as _engine_module

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.state import ConfigAttr


def _dependency_ordered_keys(
    keys: list[str],
    attr_by_vn: dict[str, "ConfigAttr"],
    rules: list[Any],
) -> list[str]:
    """Topological sort of `keys` by rule-proven attribute dependency.

    Builds a "must come before" edge condition_vn -> target_vn for
    every rule with a real DECLARATIVE condition (conditions, or a
    nonzero condition_attr_id) whose condition and target are both
    present in `keys`. Kahn's algorithm, with ConfigAttr.order
    (bm_config_attr.order_number) as the tie-break for which
    zero-remaining-dependency key is emitted next, so output stays
    deterministic and close to the catalog's own display order
    whenever no dependency constrains it either way.

    Rule ids reference attributes by their BM-native id — matches
    ConfigAttr.source_id first (falls back to entity_id), the same
    dual-id convention _attr_index already uses. Edge extraction
    itself is shared with _attribute_depth_ranks via
    _rule_condition_edges; this method applies its own `keys`
    restriction on top since only-what's-being-emitted is a payload-
    key-ordering-specific constraint.
    """
    attrs = list(attr_by_vn.values())
    predecessors_all, _successors_all, _id_to_vn = (
        _engine_module.CpqEngine._rule_condition_edges(attrs, rules)
    )

    key_set = set(keys)
    predecessors: dict[str, set[str]] = {
        target_vn: {c for c in conds if c in key_set}
        for target_vn, conds in predecessors_all.items()
        if target_vn in key_set
    }

    successors: dict[str, set[str]] = {}
    for target_vn, conds in predecessors.items():
        for c in conds:
            successors.setdefault(c, set()).add(target_vn)

    def _order_key(vn: str) -> int:
        a = attr_by_vn.get(vn)
        return a.order if a is not None else 10**9

    remaining = {vn: len(predecessors.get(vn, ())) for vn in keys}
    ready = sorted((vn for vn, n in remaining.items() if n == 0), key=_order_key)
    result: list[str] = []
    visited: set[str] = set()
    while ready:
        vn = ready.pop(0)
        if vn in visited:
            continue
        visited.add(vn)
        result.append(vn)
        newly_ready = []
        for succ in successors.get(vn, ()):
            remaining[succ] -= 1
            if remaining[succ] == 0 and succ not in visited:
                newly_ready.append(succ)
        if newly_ready:
            ready.extend(newly_ready)
            ready.sort(key=_order_key)
    # A cycle in rule data (never expected, but rule authoring can be
    # messy) leaves some keys with remaining > 0 forever — append them
    # by order_number rather than drop or crash, same "never lose a
    # key" contract the no-rules branch already has.
    leftover = sorted((vn for vn in keys if vn not in visited), key=_order_key)
    result.extend(leftover)
    return result
