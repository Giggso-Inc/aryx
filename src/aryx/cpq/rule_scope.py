"""Rule scoping by catalog-node ancestry (aryxent PR 6, flag-gated).

A BmConfigRule carries ``ref_id`` -- the BmCatalog node it is authored under.
For a multi-model catalog a rule scoped to an unrelated branch (e.g. a
hardware-upgrade subtree) must not fire for the model the customer actually
asked about. With ``cpq_rule_scope_filter_enabled`` on and a resolved model
for the turn (``model_resolution.get_turn()``), loaded rules are kept only
when ``ref_id`` is in the model's ``scope_node_ids`` (its own node plus real
ancestors).

Safe behaviour, same as aryxent: a rule with an empty/unknown ``ref_id`` is
UNBOUND and is always kept (never excluded for lack of data). The filter is
a no-op (input list returned unchanged) when the flag is off, when no turn
is bound, when the turn's model is unresolved, or when the bound turn's
workspace/catalog prefix differs from the caller's (when the caller passes
them); any internal error also falls back to the unfiltered list. A
``ref_id`` that is not a real catalog node (family-level ids, the "-1" root
sentinel) is also unbound and kept, matching ``TurnModelContext.rule_scope``.

One exception (review of #503, 2026-10-09): when the turn's model has an
EMPTY scope (no BmCatalog tree node -- true for every Data-Table-resolved
model, e.g. APX 1500/4500/6500 Enhanced, APX 6000/8000), an UNCONDITIONAL
rule (``HidingRule.always`` -- see ``cpq_empty_condition_rule_true_enabled``)
that IS scoped to a real node is excluded rather than kept. An unconditional
rule has no condition of its own to limit where it fires, so for it
specifically "nothing to scope by" cannot mean "keep it" the way it safely
does for every rule with a real condition. A conditional rule, or any rule
with an unbound ``ref_id``, is unaffected by this and keeps the plain no-op.

Known gap: the turn is bound only by the /ask flow. Callers outside /ask
(``cpq/payload_building/standalone.py``, ``graph/feature_search.py``) never
see a bound turn, so they evaluate the UNSCOPED rule list even when the chat
turn that produced the quote used the scoped one. It runs after the engine's rule cache,
so the cache keeps the full list and two turns for different models share it.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.config import get_settings
from aryx.cpq import model_resolution as _model_resolution
from aryx.cpq.model_resolution_catalog import cached as _cached_catalog
from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)

__all__ = [
    "scope_rules_by_ancestry", "scope_value_rules_tuple", "rule_scope_enabled",
    "tag_ref_ids",
]


def rule_scope_enabled() -> bool:
    """True when rule rows should be fetched with their ref_id."""
    try:
        return bool(getattr(get_settings(), "cpq_rule_scope_filter_enabled", False))
    except Exception:
        return False


def tag_ref_ids(rules: list[Any], marks: list[tuple[int, str]]) -> None:
    """Set ``ref_id`` on rules appended per source row. ``marks`` holds
    (len(rules) at the start of a row, that row's ref_id) in order."""
    for i, (start, ref) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(rules)
        if not ref:
            continue
        for rule in rules[start:end]:
            rule.ref_id = ref


def scope_rules_by_ancestry(
    rules: list, list_name: str,
    workspace_id: int | None = None, catalog_prefix: str | None = None,
) -> list:
    """Keep rules whose ref_id is in the resolved model's scope or unbound.
    ``workspace_id``/``catalog_prefix``, when given, must match the bound
    turn's or the list is returned unfiltered (stale/foreign binding)."""
    if not rule_scope_enabled():
        return rules
    try:
        ctx = _model_resolution.get_turn()
        if ctx is None or not ctx.resolution.resolved or ctx.resolution.chosen is None:
            return rules
        if workspace_id is not None and int(workspace_id) != int(ctx.workspace_id):
            return rules
        if catalog_prefix is not None and (catalog_prefix or "") != (ctx.catalog_prefix or ""):
            return rules
        scope = ctx.resolution.scope_node_ids
        catalog = _cached_catalog(ctx.workspace_id, ctx.catalog_prefix)
        known = catalog.nodes_by_id if catalog is not None else None
        if not scope:
            # An unconditional rule has no condition of its own to limit
            # where it fires, so it can't inherit the plain "nothing to
            # scope by" no-op the way an ordinary conditional rule safely
            # does. See docs/cpq/CPQ_RULE_KEY_MARKED_ATTR_RESOLUTION_2026_10_09.md
            # for the live case this closes (PR #503 review). Returns the
            # original `rules` object (not a copy) when nothing is actually
            # excluded, preserving the `is rules` no-op contract every other
            # caller/test relies on.
            filtered = [
                r for r in rules
                if not (
                    bool(getattr(r, "always", False))
                    and (getattr(r, "ref_id", "") or "") not in ("", "-1")
                    and (known is None or (getattr(r, "ref_id", "") or "") in known)
                )
            ]
            return rules if len(filtered) == len(rules) else filtered

        def _keep(rule: Any) -> bool:
            ref = getattr(rule, "ref_id", "") or ""
            if not ref or ref == "-1" or ref in scope:
                return True
            return known is not None and ref not in known

        kept = [r for r in rules if _keep(r)]
        if ctx.first_time(("rule_scope_filter", list_name)):
            logger.info(
                "cpq_diag: model_scope rule_scope_filter list=%r total=%d "
                "kept=%d model=%r",
                list_name, len(rules), len(kept), ctx.resolution.chosen.cpq_model,
            )
            raven_log("INFO", "P4", "ask.rule_scope.filtered rules kept for the resolved model",
                      context={"actor": "rule_scope", "requested_action": "load_rules", "resource": list_name,
                               "required_permission": "ref_id_in_model_scope", "decision": "filtered",
                               "reason_code": "MODEL_SCOPE", "policy_version": "rule_scope_v1",
                               "cpq_model": ctx.resolution.chosen.cpq_model, "rules_total": len(rules),
                               "rules_in_scope_for_model": len(kept), "rules_excluded": len(rules) - len(kept),
                               "scope_nodes": len(scope)})
        return kept
    except Exception as exc:
        logger.exception(
            "cpq_diag: model_scope rule_scope_filter failed list=%r "
            "(falling back to unfiltered rules)", list_name,
        )
        raven_log("WARN", "P3", "ask.rule_scope.failed falling back to unfiltered rules",
                  error_code="ARYX_ASK_RULE_SCOPE_FAILED",
                  context={"resource": list_name, "triggering_error": type(exc).__name__, "attempt": 1,
                           "max_attempts": 1, "backoff_ms": 0, "recovery_selected": "unfiltered_rules",
                           "fallback_target": "all_rules", "exit_condition": "degraded", "result": "degraded",
                           "rules_total": len(rules)})
        return rules


def scope_value_rules_tuple(
    result: tuple, workspace_id: int | None = None, catalog_prefix: str | None = None,
) -> tuple:
    """`scope_rules_by_ancestry` over `_load_value_rules`'s 4-tuple
    (rec, con, validation, value-less hiding)."""
    rec, con, val, hid = result
    return (
        scope_rules_by_ancestry(rec, "recommendation_rules", workspace_id, catalog_prefix),
        scope_rules_by_ancestry(con, "constraint_rules", workspace_id, catalog_prefix),
        scope_rules_by_ancestry(val, "validation_rules", workspace_id, catalog_prefix),
        scope_rules_by_ancestry(hid, "value_less_hiding_rules", workspace_id, catalog_prefix),
    )
