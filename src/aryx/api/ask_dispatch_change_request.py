"""CHANGE_REQUEST, CHANGE_TARGET_WITHOUT_VALUE, and CHANGE_REQUESTS_MULTI
branches of `_dispatch_intent_result`, split out of `api/ask_api.py`
(Phase 7/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). Logic unchanged from the original inline `if`
blocks. `_with_classify_usage` is read through the ask_api MODULE object
(not imported by name) since ask_api tests patch several of its own
module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_attr_query_and_classify_usage import _with_classify_usage
from aryx.api.ask_build_no_value_response import _build_no_value_response
from aryx.api.ask_handle_cascade import _handle_cascade
from aryx.api.ask_handle_cascade_multi import _handle_cascade_multi
from aryx.api.ask_target_description import _resolve_target_description


def _dispatch_change_request(
    result: Any, req: "Any", session: Any, attrs: list,
    hiding_rules: list, rec_rules: list, con_rules: list,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any] | None:
    """CHANGE_REQUEST: dispatched to the SAME `_handle_cascade` the regex
    path already uses. The plain-language `new_value_description` is
    passed through UNRESOLVED as the `new_value_hint` — that handler
    already calls `apply_answer` internally to turn a hint into a real
    item_value and already has its own "couldn't match that" fallback, so
    there is no separate resolution step to duplicate here. Target
    resolution (for CHANGE_REQUEST's own target ATTR, not its value) uses
    `_resolve_target_description` — 0 or 2+ candidates both mean
    "unresolved," returned as None here, never guessed.
    """
    if not result.target or not result.target.new_value_description:
        return None
    attr, _candidates = _resolve_target_description(
        result.target.target_description, attrs)
    if attr is None:
        return None
    return _with_classify_usage(
        _handle_cascade(
            req, session, attrs, attr, result.target.new_value_description,
            hiding_rules, rec_rules, con_rules,
        ),
        classify_prompt_tokens, classify_completion_tokens,
    )


def _dispatch_change_target_without_value(
    result: Any, req: "Any", session: Any, attrs: list,
    con_rules: list, bml_eval: Any,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any] | None:
    """CHANGE_TARGET_WITHOUT_VALUE (2026-07-28 addition): dispatched to
    the SAME `_build_no_value_response` helper the regex-based `detect_
    change_target_without_value` and the LLM change-intent fallback's own
    empty-value case already share. Live-verified need: "change the
    hardware type" — where "hardware type" doesn't literally contain
    "version" so no regex label-match ever fires — is correctly
    classified by the universal classifier (rarity-weighted candidate
    scoring, see `_relevant_intent_candidates`) as CHANGE_TARGET_WITHOUT_
    VALUE naming hWVersion_astro; without this branch that correct
    classification was silently discarded and the turn fell through to
    the generic "I didn't quite catch that" nudge.
    """
    if not result.target:
        return None
    attr, _candidates = _resolve_target_description(
        result.target.target_description, attrs)
    if attr is None:
        return None
    return _with_classify_usage(
        _build_no_value_response(
            req, session, attrs, attr, con_rules, bml_eval,
            "cpq_llm_first_change_target_no_value",
        ),
        classify_prompt_tokens, classify_completion_tokens,
    )


def _dispatch_change_requests_multi(
    result: Any, req: "Any", session: Any, attrs: list,
    hiding_rules: list, rec_rules: list, con_rules: list,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any] | None:
    """CHANGE_REQUESTS_MULTI: dispatched to the SAME `_handle_cascade_
    multi` the regex-based CHANGE_REQUESTS_MULTI path already uses —
    resolved the same way `_dispatch_change_request` resolves a single
    target, just for every named target at once. Needs 2+ resolved
    matches to proceed; a single resolvable target here would be a
    structurally malformed multi-result, never guessed at.
    """
    if not result.targets:
        return None
    matches = []
    for t in result.targets:
        if not t.new_value_description:
            continue
        attr, _candidates = _resolve_target_description(t.target_description, attrs)
        if attr is not None:
            matches.append((attr, t.new_value_description))
    if len(matches) < 2:
        return None
    return _with_classify_usage(
        _handle_cascade_multi(
            req, session, attrs, matches, hiding_rules, rec_rules, con_rules,
        ),
        classify_prompt_tokens, classify_completion_tokens,
    )
