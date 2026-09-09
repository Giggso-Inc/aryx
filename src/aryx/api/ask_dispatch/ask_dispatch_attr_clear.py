"""ATTR_CLEAR branch of `_dispatch_intent_result`, split out of `api/
ask_api.py` (Phase 7/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original inline
`if` block. `_cpq_engine` and `_with_classify_usage` are read through
the ask_api MODULE object (not imported by name) since ask_api tests
patch several of its own module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_attr_recompute.ask_attr_query_and_classify_usage import _with_classify_usage
from aryx.api.ask_handle.ask_handle_attr_clear import _handle_attr_clear
from aryx.api.ask_catalog.ask_target_description import _resolve_target_description


def _dispatch_attr_clear(
    result: Any, req: "Any", session: Any, attrs: list,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any] | None:
    """Same reasoning as ATTR_ACTIVATION, for ATTR_CLEAR: re-verify the
    exact eligibility predicate detect_attr_clear itself uses — not
    required, single-select, already filled, AND a trial removal
    confirms no recommendation rule would immediately refill it and no
    constraint rule would narrow it to exactly one forced option
    (clearing would otherwise silently no-op, the same "never a no-op
    disguised as an action" discipline detect_attr_clear's own
    docstring describes).
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    if not result.target:
        return None
    attr, _candidates = _resolve_target_description(
        result.target.target_description, attrs)
    if attr is None:
        return None
    if attr.required or attr.select_type == "multi":
        return None
    if not session.filled.get(attr.variable_name):
        return None
    _trial_filled = dict(session.filled)
    _trial_filled.pop(attr.variable_name, None)
    _rec_fires = _cpq_engine.apply_recommendation_rules(
        attrs, _trial_filled, rec_rules, bml_eval=bml_eval)
    if attr.variable_name in _rec_fires:
        return None
    _constrained = _cpq_engine.apply_constraint_rules(
        attrs, con_rules, _trial_filled, bml_eval=bml_eval)
    _allowed = _constrained.get(attr.entity_id)
    if _allowed is not None:
        _valid_opts = [o for o in attr.options if o.item_value in _allowed]
        if len(_valid_opts) == 1:
            return None
    return _with_classify_usage(
        _handle_attr_clear(
            req, session, attrs, attr, hiding_rules, rec_rules, con_rules,
        ),
        classify_prompt_tokens, classify_completion_tokens,
    )
