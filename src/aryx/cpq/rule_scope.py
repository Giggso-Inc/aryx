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
is bound, or when the turn's model is unresolved; any internal error also
falls back to the unfiltered list. It runs after the engine's rule cache,
so the cache keeps the full list and two turns for different models share it.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.config import get_settings
from aryx.cpq import model_resolution as _model_resolution

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


def scope_rules_by_ancestry(rules: list, list_name: str) -> list:
    """Keep rules whose ref_id is in the resolved model's scope or unbound."""
    if not rule_scope_enabled():
        return rules
    try:
        ctx = _model_resolution.get_turn()
        if ctx is None or not ctx.resolution.resolved or ctx.resolution.chosen is None:
            return rules
        scope = ctx.resolution.scope_node_ids
        kept = [r for r in rules
                if not getattr(r, "ref_id", "") or r.ref_id in scope]
        if ctx.first_time(("rule_scope_filter", list_name)):
            logger.info(
                "cpq_diag: model_scope rule_scope_filter list=%r total=%d "
                "kept=%d model=%r",
                list_name, len(rules), len(kept), ctx.resolution.chosen.cpq_model,
            )
        return kept
    except Exception:
        logger.exception(
            "cpq_diag: model_scope rule_scope_filter failed list=%r "
            "(falling back to unfiltered rules)", list_name,
        )
        return rules


def scope_value_rules_tuple(result: tuple) -> tuple:
    """`scope_rules_by_ancestry` over `_load_value_rules`'s 4-tuple
    (rec, con, validation, value-less hiding)."""
    rec, con, val, hid = result
    return (
        scope_rules_by_ancestry(rec, "recommendation_rules"),
        scope_rules_by_ancestry(con, "constraint_rules"),
        scope_rules_by_ancestry(val, "validation_rules"),
        scope_rules_by_ancestry(hid, "value_less_hiding_rules"),
    )
