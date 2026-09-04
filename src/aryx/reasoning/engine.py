"""Forward-chaining rule evaluator over the workspace entity store.

Rule DSL (JSON):
  when: {"type": "Customer", "attr": "revenue", "op": ">", "value": 1000000}
  then: {"set_label": "Platinum"}  OR  {"add_relationship": "TIER_MEMBER",
                                        "target_type": "Tier",
                                        "target_name": "Platinum"}

Each match writes either a label attribute (`inferred_label`) on the source
entity in FalkorDB or an INF_<NAME> edge between two entities. The evaluator
is idempotent — re-running over the same data produces the same graph.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), the
parametrized rule-matching/graph-write functions (`_match`/`_apply_label`/
`_apply_edge`/`_fire`) moved to `reasoning/engine_rules.py` (zero patch
risk — see that module's docstring). `evaluate_workspace` stays here as
a deliberate exception: `get_settings`/`RuleStore`/`EntityStore`/
`FalkorStore`/`ws_graph` are all directly whitebox-patched
(`aryx.reasoning.engine.*`) by `tests/test_scalability_fixes.py` and
called only from this function.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.config import get_settings
from aryx.graph.falkor_store import FalkorStore
from aryx.reasoning.edge_axioms import apply_edge_axiom as _apply_edge_axiom
from aryx.reasoning.engine_rules import _apply_edge, _apply_label, _fire, _match
from aryx.store.entity_store import EntityStore
from aryx.store.rule_store import RuleStore
from aryx.workspaces import ws_graph

__all__ = [
    "_apply_edge",
    "_apply_label",
    "_fire",
    "_match",
    "evaluate_workspace",
]

logger = logging.getLogger(__name__)


def evaluate_workspace(workspace_id: int) -> dict[str, Any]:
    """Apply every enabled rule against the workspace; return per-rule fire counts."""
    settings = get_settings()
    rules_store = RuleStore(settings.effective_dsn())
    try:
        rules = [r for r in rules_store.list_(workspace_id) if r["enabled"]]
    finally:
        rules_store.close()
    if not rules:
        return {"rules_evaluated": 0, "total_fires": 0, "per_rule": {}}
    threshold = settings.rules_db_warn_threshold
    if len(rules) > threshold:
        logger.warning(
            "evaluate_workspace ws=%s rules=%d exceeds threshold=%d — "
            "each rule issues one DB round-trip; revisit batching or "
            "set ARYX_RULES_DB_WARN_THRESHOLD to suppress",
            workspace_id, len(rules), threshold,
        )
    estore = None
    bumps = None
    try:
        estore = EntityStore(settings.effective_dsn(), workspace_id)
        graph = FalkorStore(settings.graph_url, ws_graph(workspace_id))
        per_rule: dict[str, int] = {}
        total = 0
        bumps = RuleStore(settings.effective_dsn())
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
