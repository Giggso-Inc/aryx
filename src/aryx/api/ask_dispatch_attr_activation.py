"""ATTR_ACTIVATION branch of `_dispatch_intent_result`, split out of
`api/ask_api.py` (Phase 7/11-phase ask_api decomposition, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original
inline `if` block. `_cpq_engine` and `_with_classify_usage` are read
through the ask_api MODULE object (not imported by name) since ask_api
tests patch several of its own module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module
from aryx.api.ask_handle_attr_activation import _handle_attr_activation
from aryx.api.ask_target_description import _resolve_target_description


def _dispatch_attr_activation(
    result: Any, req: "Any", session: Any, attrs: list,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any] | None:
    """docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md Phase 2b
    follow-up: now that intent_gateway._deterministic_mutating_signals
    genuinely probes ATTR_ACTIVATION (real detect_attr_activation calls,
    not permanently empty), a mapped result here has ALSO already passed
    real deterministic agreement upstream — same shape as MULTI_SELECT_
    REMOVAL, no extra Confidence.HIGH gate needed.
    `_resolve_target_description` only proves the label is unique; it
    says nothing about whether the attr is currently ELIGIBLE for
    activation. Re-verified here against the exact same predicate
    detect_attr_activation itself uses — not required, not attr.hidden,
    not already filled/selected, and not currently excluded by a
    live-evaluated hiding rule — so a stale or since-changed session
    state can never activate an attr the regex path would have silently
    declined.
    """
    if not result.target:
        return None
    attr, _candidates = _resolve_target_description(
        result.target.target_description, attrs)
    if attr is None:
        return None
    if attr.required or attr.hidden:
        return None
    if attr.variable_name in session.filled or session.filled_multi.get(attr.variable_name):
        return None
    _hidden_now = _ask_api_module._cpq_engine.apply_hiding_rules(
        attrs, session.filled, hiding_rules, bml_eval=bml_eval,
        filled_multi=session.filled_multi,
    )[2]
    if attr.variable_name in _hidden_now:
        return None
    return _ask_api_module._with_classify_usage(
        _handle_attr_activation(
            req, session, attrs, attr, hiding_rules, rec_rules, con_rules,
        ),
        classify_prompt_tokens, classify_completion_tokens,
    )
