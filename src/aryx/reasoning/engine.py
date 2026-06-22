"""Forward-chaining rule evaluator over the workspace entity store.

Rule DSL (JSON):
  when: {"type": "Customer", "attr": "revenue", "op": ">", "value": 1000000}
  then: {"set_label": "Platinum"}  OR  {"add_relationship": "TIER_MEMBER",
                                        "target_type": "Tier",
                                        "target_name": "Platinum"}

Each match writes either a label attribute (`inferred_label`) on the source
entity in FalkorDB or an INF_<NAME> edge between two entities. The evaluator
is idempotent — re-running over the same data produces the same graph.
"""
from __future__ import annotations

import logging
import re
from typing import Any

# Relationship names interpolated into Cypher must be safe identifiers.
_REL_NAME_RE = re.compile(r"^[A-Z0-9_]+$")

from aryx.config import get_settings
from aryx.graph.falkor_store import FalkorStore
from aryx.store.entity_store import EntityStore
from aryx.store.rule_store import RuleStore
from aryx.workspaces import ws_graph

logger = logging.getLogger(__name__)

_OPS = {
    ">":  lambda a, b: float(a) > float(b),
    ">=": lambda a, b: float(a) >= float(b),
    "<":  lambda a, b: float(a) < float(b),
    "<=": lambda a, b: float(a) <= float(b),
    "==": lambda a, b: str(a) == str(b),
    "!=": lambda a, b: str(a) != str(b),
    "contains": lambda a, b: str(b).lower() in str(a or "").lower(),
}


def _match(entity: dict, when: dict) -> bool:
    """Test one entity against one when-clause."""
    if when.get("type") and entity.get("type") != when["type"]:
        return False
    attr = when.get("attr")
    if not attr:
        # type-only rule: SQL already filtered by type, no attribute condition
        return True
    op = _OPS.get(when.get("op", "=="))
    if op is None:
        return False
    val = (entity.get("attributes") or {}).get(attr)
    if val is None:
        return False
    try:
        return op(val, when.get("value"))
    except (TypeError, ValueError):
        return False


def _apply_label(graph: FalkorStore, entity_id: int, label: str) -> None:
    """Write an inferred_label attribute on the entity in FalkorDB."""
    graph.run(
        "MATCH (n {id: $id}) SET n.inferred_label = $label",
        params={"id": int(entity_id), "label": str(label)},
    )


def _apply_edge(graph: FalkorStore, source_id: int, name: str,
                target_type: str, target_name: str) -> None:
    """Create an INF_-prefixed edge to a target entity (matched by type+name)."""
    safe = name.upper()
    if not _REL_NAME_RE.match(safe):
        raise ValueError(
            f"Invalid relationship name {name!r}: must match [A-Z0-9_]+"
        )
    rel = f"INF_{safe}"
    graph.run(
        "MATCH (s {id: $sid}), (t {ontology_type: $ttype, name: $tname}) "
        f"MERGE (s)-[r:{rel} {{inferred: true}}]->(t)",
        params={"sid": int(source_id), "ttype": target_type,
                "tname": target_name},
    )


def _fire(graph: FalkorStore, entity: dict, then: dict) -> int:
    """Apply the then-clause; return 1 on success, 0 on no-op."""
    eid = int(entity.get("id", 0))
    if not eid:
        return 0
    if "set_label" in then:
        _apply_label(graph, eid, str(then["set_label"]))
        return 1
    if "add_relationship" in then:
        _apply_edge(
            graph, eid, str(then["add_relationship"]),
            str(then.get("target_type", "")),
            str(then.get("target_name", "")),
        )
        return 1
    return 0


from aryx.reasoning.edge_axioms import apply_edge_axiom as _apply_edge_axiom


def evaluate_workspace(workspace_id: int) -> dict[str, Any]:
    """Apply every enabled rule against the workspace; return per-rule fire counts."""
    settings = get_settings()
    rules_store = RuleStore(settings.rdb_dsn)
    try:
        rules = [r for r in rules_store.list_(workspace_id) if r["enabled"]]
    finally:
        rules_store.close()
    if not rules:
        return {"rules_evaluated": 0, "total_fires": 0, "per_rule": {}}
    estore = None
    bumps = None
    try:
        estore = EntityStore(settings.rdb_dsn, workspace_id)
        graph = FalkorStore(settings.graph_url, ws_graph(workspace_id))
        per_rule: dict[str, int] = {}
        total = 0
        bumps = RuleStore(settings.rdb_dsn)
        for rule in rules:
            when = rule.get("when") or {}
            then = rule.get("then") or {}
            fires = 0
            try:
                if "edge" in when:
                    # Edge-scoped axiom (inverse_of / symmetric / transitive).
                    fires = _apply_edge_axiom(graph, str(when["edge"]), then)
                else:
                    if when.get("type") or when.get("attr"):
                        for ent in estore.match_entities(when):
                            if _match(ent, when):
                                fires += _fire(graph, ent, then)
                    else:
                        logger.warning(
                            "rule %r skipped — when-clause has no 'type', 'attr', or 'edge'",
                            rule.get("name"),
                        )
            except ValueError as exc:
                logger.warning(
                    "rule %r skipped — invalid value in then-clause: %s",
                    rule.get("name"), exc,
                )
            per_rule[rule["name"]] = fires
            total += fires
            if fires:
                bumps.bump(workspace_id, rule["name"], fires)
    finally:
        if bumps is not None:
            bumps.close()
        if estore is not None:
            estore.close()
    logger.info("evaluator ws=%s fires=%d rules=%d",
                workspace_id, total, len(rules))
    return {"rules_evaluated": len(rules), "total_fires": total,
            "per_rule": per_rule}
