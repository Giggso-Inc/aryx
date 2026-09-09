"""MULTI_SELECT_REMOVAL branch of `_dispatch_intent_result`, split out of
`api/ask_api.py` (Phase 7/11-phase ask_api decomposition, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original
inline `if` block. `_cpq_engine` and `_with_classify_usage` are read
through the ask_api MODULE object (not imported by name) since ask_api
tests patch several of its own module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_attr_query_and_classify_usage import _with_classify_usage
from aryx.api.ask_handle.ask_handle_multi_select_removal import _handle_multi_select_removal
from aryx.api.ask_target_description import _resolve_target_description


def _dispatch_multi_select_removal(
    result: Any, req: "Any", session: Any, attrs: list,
    hiding_rules: list, rec_rules: list, con_rules: list,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any] | None:
    """docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md Phase 2b:
    MULTI_SELECT_REMOVAL IS in intent_gateway.MUTATING_CATEGORIES and IS
    genuinely probed by _deterministic_mutating_signals — so a mapped
    result here already passed real deterministic agreement upstream,
    before `_gw.action` was ever set to "dispatch". No extra
    Confidence.HIGH gate needed the way ATTR_QUERY/QA_QUESTION require,
    since this category already has the stronger protection.

    `_resolve_target_description` only proves the ATTRIBUTE label is
    unique — it says nothing about the OPTION the LLM identified for
    removal. Two more things must hold, mirroring detect_multi_select_
    removal's own invariants exactly: the attr must actually be a
    multi-select, and the named option must resolve to a real
    `item_value` that is CURRENTLY SELECTED — naming an unselected
    option, or one that doesn't exist at all, is never a removal
    request (never guessed).
    """
    if not result.target or not result.target.new_value_description:
        return None
    attr, _candidates = _resolve_target_description(
        result.target.target_description, attrs)
    if attr is None or attr.select_type != "multi":
        return None
    _current_selection = session.filled_multi.get(attr.variable_name, [])
    _wanted_display = result.target.new_value_description.strip().lower()
    _resolved_iv = next(
        (o.item_value for o in attr.options
         if o.display_name.strip().lower() == _wanted_display
         and o.item_value in _current_selection),
        None,
    )
    if _resolved_iv is None:
        return None
    return _with_classify_usage(
        _handle_multi_select_removal(
            req, session, attrs, attr, [_resolved_iv],
            hiding_rules, rec_rules, con_rules,
        ),
        classify_prompt_tokens, classify_completion_tokens,
    )
