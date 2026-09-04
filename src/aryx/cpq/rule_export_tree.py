"""Product tree data type + name-indexing/leaf-walking helpers for
rule-catalog export.

Split out of `cpq/rule_export.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). `build_product_tree` itself stays in the hub — it calls
`get_cpq_rdb()`, and `tests/test_cpq_rule_export.py` patches
`aryx.cpq.rule_export.get_cpq_rdb`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TreeNode:
    native_id: str
    parent_id: str
    name: str
    children: list["TreeNode"]


def _normalize(value: str) -> str:
    """Exact-match key: case-fold + collapse whitespace. NOT fuzzy matching
    -- a real casing divergence (e.g. '700/800 MHz' vs '700/800 MHZ') still
    normalizes to the SAME key here on purpose (both differ only in case),
    which is the one and only normalization this classifier performs.
    Anything more permissive (partial match, edit distance) is explicitly
    out of scope -- see docs/CPQ_RULE_EXPORT_AND_TRACE_TDD_PLAN.md §8."""
    return " ".join((value or "").strip().split()).upper()


def _name_index(tree: dict[str, TreeNode]) -> dict[str, TreeNode]:
    """{normalized name: node} -- ambiguous duplicate names are dropped
    (never guess which one a rule's condition_value meant)."""
    by_name: dict[str, TreeNode] = {}
    ambiguous: set[str] = set()
    for node in tree.values():
        key = _normalize(node.name)
        if key in by_name and by_name[key].native_id != node.native_id:
            ambiguous.add(key)
        else:
            by_name[key] = node
    for key in ambiguous:
        by_name.pop(key, None)
    return by_name


def _leaf_names(node: TreeNode) -> list[str]:
    """Model (leaf) names under `node` -- `node.name` itself only when it
    IS a leaf (no children); otherwise every leaf beneath it, never the
    intermediate family/line name itself."""
    if not node.children:
        return [node.name]
    names: list[str] = []
    for child in node.children:
        names.extend(_leaf_names(child))
    return names
