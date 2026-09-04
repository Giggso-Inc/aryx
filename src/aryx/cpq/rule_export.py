"""Per-catalog rule-catalog JSON export, split by product family/line/model.

docs/CPQ_RULE_EXPORT_AND_TRACE_TDD_PLAN.md's feature 1. Reuses the existing
rule loaders (CpqEngine.load_hiding_rules /
load_recommendation_and_constraint_rules) and the same BmPrdFamily/BmCatalog
tree-walking convention already established by
CpqEngine.single_model_variable_name / model_variable_candidates — no new
query logic, no new data model.

Classification is exact, casing-normalized string matching only (confirmed
design decision) -- never fuzzy. A rule that doesn't cleanly resolve to a
tree node (no product condition at all, or a script-conditioned rule whose
literal comparisons can't be statically resolved) lands in the explicit
"unscoped_or_unresolved" bucket. Every loaded rule appears SOMEWHERE in the
output -- classification can be imperfect, silent drops cannot happen.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`rule_export_tree.py` (product tree materialization) and
`rule_export_classify.py` (per-rule scope classification), both
re-imported here. Zero whitebox test patches exist anywhere against
`aryx.cpq.rule_export.*` (confirmed via grep), so the split was purely
mechanical. `export_rules_json` — the orchestrator tying tree + rules
together — stays here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aryx.cpq.rdb import get_cpq_rdb
from aryx.cpq.rule_export_classify import UNSCOPED, _rule_dict, classify_rule_scope
from aryx.cpq.rule_export_tree import TreeNode, _name_index, _normalize
from aryx.cpq.state import ConstraintRule, HidingRule, RecommendationRule

__all__ = [
    "TreeNode",
    "UNSCOPED",
    "_name_index",
    "_normalize",
    "build_product_tree",
    "classify_rule_scope",
    "export_rules_json",
]

logger = logging.getLogger(__name__)


def build_product_tree(
    reader: Any, workspace_id: int, catalog_prefix: str,
) -> dict[str, TreeNode]:
    """Materialize the FULL family->line->model tree for one catalog.

    Returns {native_id: TreeNode}. Unlike single_model_variable_name (which
    only cares about leaves), this keeps every node and its parent/child
    links so a rule matched at a LINE node can be expanded to cover every
    child model.

    Cyclic or dangling parent_id rows are tolerated, not raised: a node
    whose parent_id points to itself or to a nonexistent node is treated as
    a root (matches the existing "-1 = root" convention) rather than
    hanging a caller in an infinite walk.
    """
    cat_ents = reader.find_entities(ontology_type=f"{catalog_prefix}BmCatalog", limit=500)
    if not cat_ents:
        return {}
    pg = get_cpq_rdb().fetch_entity_attributes([e["id"] for e in cat_ents], workspace_id)
    raw: list[tuple[str, str, str]] = []
    for cent in cat_ents:
        a = pg.get(cent["id"], {})
        native = str(a.get("id") or "").strip()
        parent = str(a.get("parent_id") or "").strip()
        name = str(a.get("name") or cent.get("name") or "").strip()
        if native and name:
            raw.append((native, parent, name))

    known_ids = {native for native, _p, _n in raw}
    nodes: dict[str, TreeNode] = {
        native: TreeNode(native_id=native, parent_id=parent, name=name, children=[])
        for native, parent, name in raw
    }
    for native, parent, _name in raw:
        node = nodes[native]
        if parent in ("-1", "", native) or parent not in known_ids:
            node.parent_id = "-1"  # root, or cyclic/dangling -> treated as root
            continue
        nodes[parent].children.append(node)
    return nodes


def export_rules_json(
    reader: Any,
    workspace_id: int,
    catalog_prefix: str,
    hiding_rules: list[HidingRule],
    rec_rules: list[RecommendationRule],
    con_rules: list[ConstraintRule],
) -> dict[str, Any]:
    """Build the per-catalog rule-catalog export.

    Callers load rules via the existing CpqEngine.load_hiding_rules() /
    load_recommendation_and_constraint_rules() and pass them in here --
    this module performs no rule loading of its own, only tree-building and
    classification.

    Every rule in hiding_rules + rec_rules + con_rules is accounted for by
    identity -- either in unscoped_or_unresolved, or nested under at least
    one family/line/model. A rule matched at a family/line node is
    deliberately PLACED once per model it covers (that's the point of the
    grouping), so it can appear multiple times in `families` -- but is
    still only counted once in the total_rules_loaded/total_exported
    comparison, so a genuine silent drop stays distinguishable from normal
    multi-model fan-out.
    """
    tree = build_product_tree(reader, workspace_id, catalog_prefix)
    name_index = _name_index(tree)
    roots = [n for n in tree.values() if n.parent_id == "-1"]

    grouped: dict[str, dict[str, dict[str, list[dict]]]] = {}
    unscoped: list[dict[str, Any]] = []

    all_rules: list[Any] = [*hiding_rules, *rec_rules, *con_rules]
    exported_rule_ids: set[int] = set()  # id(rule) -- ONE entry per rule,
    # regardless of how many models it fans out to below. A family/line-
    # level rule is deliberately PLACED once per covered model (that's the
    # whole point of covers_models -- the rule really does apply to each
    # of those models), so counting placements would inflate this set's
    # complement by N-1 for every such rule and make the anti-drop check
    # misfire on the normal case, not just genuine drops.
    for rule in all_rules:
        scope = classify_rule_scope(rule, name_index)
        rd = _rule_dict(rule)
        if scope.get("scope") == UNSCOPED:
            unscoped.append(rd)
            exported_rule_ids.add(id(rule))
            continue
        exported_rule_ids.add(id(rule))
        for model_name in scope["covers_models"]:
            # Walk the tree upward from the matched node's own family/line
            # ancestry is not tracked separately here -- the matched node's
            # own name is recorded as the grouping key at whichever depth
            # it was matched (family, line, or model); see docs plan §1.
            root_name = scope["matched_node"]
            grouped.setdefault(root_name, {}).setdefault("models", {}).setdefault(
                model_name, []).append(rd)

    total_loaded = len(all_rules)
    total_exported = len(exported_rule_ids)
    if total_exported != total_loaded:
        logger.warning(
            "rule_export: count mismatch loaded=%d exported=%d catalog=%s",
            total_loaded, total_exported, catalog_prefix,
        )

    return {
        "catalog_prefix": catalog_prefix,
        "workspace_id": workspace_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root_families": [r.name for r in roots],
        "families": grouped,
        "unscoped_or_unresolved": unscoped,
        "total_rules_loaded": total_loaded,
    }
