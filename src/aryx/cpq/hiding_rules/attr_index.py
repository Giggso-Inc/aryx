"""Rule-id → attr / rule-id → filled-value index helpers (Phase 4 step 4
extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Stateless and purely functional -- no ``CpqEngine`` instance needed.
"""

from __future__ import annotations

from aryx.cpq.state import ConfigAttr


def _attr_index(attrs: list[ConfigAttr]) -> dict[int, ConfigAttr]:
    """Index attrs by BOTH ids rules may reference.

    Rule inputs/actions carry BM-native attribute ids from the source
    system (ConfigAttr.source_id); legacy data may reference the aryx
    entity id directly. source_id wins on collision because that is what
    BigMachines rules actually use.
    """
    idx: dict[int, ConfigAttr] = {}
    for a in attrs:
        idx.setdefault(a.entity_id, a)
    for a in attrs:
        if a.source_id is not None:
            idx[a.source_id] = a
    return idx


def _filled_by_rule_id(
    attrs: list[ConfigAttr], filled: dict[str, str],
    filled_multi: dict[str, list[str]] | None = None,
) -> dict[int, str]:
    """Map every id a rule may reference → the attr's filled value.

    select_type=="multi" attrs' current selections live in filled_multi
    (a separate structure from the scalar filled dict — see
    evaluate_rules_loop's docstring), not in `filled`. Joined here into
    a single "~"-delimited string so bml._operator_hit's set-
    intersection check (operators "7"/"8" — docs/CPQ_DECLARATIVE_
    CONDITION_OPERATOR_PLAN_2026_08_05.md Phase 2) sees the real
    current selection set instead of always finding the condition
    attribute missing. An explicitly-emptied multi-select (filled_multi
    holding []) still maps to "" here rather than being omitted — that
    is a known, real "nothing selected" state, not an unfilled one.
    """
    multi = filled_multi or {}
    out: dict[int, str] = {}
    for a in attrs:
        if a.variable_name in multi:
            val = "~".join(multi[a.variable_name])
        elif a.variable_name in filled:
            val = filled[a.variable_name]
        else:
            continue
        out[a.entity_id] = val
        if a.source_id is not None:
            out[a.source_id] = val
    return out
