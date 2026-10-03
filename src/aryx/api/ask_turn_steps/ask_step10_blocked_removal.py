"""STEP 5b: removal while blocked with no pending question, split out
of `_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). `session.pending_
variables` is empty whenever the previous turn ended on
unresolved_grid_quantity_options' block (a selected grid option has no
resolvable per-row quantity attr) rather than on a genuine next
question, so STEP 5 never fires and the turn fell straight to STEP 3
with filled_multi unchanged, re-hitting the identical block
(live-verified bug, 2026-07-22: "okay remove it" was silently discarded
this way). Tried here, before STEP 3 re-runs the loop. Logic unchanged
from the original inline block. Every ask_api name below is read
through the module object (not imported by name) since tests patch
several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.intent_schema.intent_schema_enums import IntentCategory

from aryx.api.ask_handle import ask_handle_multi_select_removal as _ask_handle_multi_select_removal_module
from aryx.api import ask_shadow_classify_and_confirm_intent as _ask_shadow_classify_and_confirm_intent_module
from aryx.raven_log import raven_log

_REMOVAL_OPTIONS = ["skip", "named_removal", "pronoun_gap_removal", "continue"]


def _step10_blocked_removal_gap(
    req: "Any", session: Any, attrs: list, hiding_rules: list, rec_rules: list,
    con_rules: list, bml_eval: Any, catalog_prefix: str, mode_request: str | None,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn resolved a removal while
    blocked with no pending question; None otherwise, in which case the
    caller continues to STEP 3.
    """
    from aryx.api import ask_api as _ask_api_module
    if session.pending_variables or session.turn <= 1 or mode_request:
        raven_log("DEBUG", "P4", "ask.removal.blocked_gap skipped", context={
            "selected_option": "skip", "available_options": _REMOVAL_OPTIONS,
            "reason_code": (
                "PENDING_PRESENT" if getattr(session, "pending_variables", None)
                else "MODE_REQUEST" if mode_request else "FIRST_TURN"),
            "pending_count": len(getattr(session, "pending_variables", None) or []),
            "mode_request": mode_request, "turn": getattr(session, "turn", None)})
        return None
    _cpq_engine = _ask_api_module._cpq_engine

    _gap_removal_match = _cpq_engine.detect_multi_select_removal(
        req.question, attrs, session.filled_multi)
    if _gap_removal_match and _ask_shadow_classify_and_confirm_intent_module._llm_confirm_deterministic_intent(
        req, session, attrs, IntentCategory.MULTI_SELECT_REMOVAL,
        hiding_rules, rec_rules, con_rules, bml_eval, catalog_prefix,
        expected_variable_name=_gap_removal_match[0].variable_name,
    ):
        _gap_attr, _gap_to_remove = _gap_removal_match
        raven_log("INFO", "P4", "ask.removal.blocked_gap named option removal handled the turn", context={
            "selected_option": "named_removal", "available_options": _REMOVAL_OPTIONS,
            "reason_code": "NAMED_REMOVAL_CONFIRMED",
            "target_field": getattr(_gap_attr, "variable_name", None),
            "remove_count": len(_gap_to_remove or []), "turn": getattr(session, "turn", None)})
        return _ask_handle_multi_select_removal_module._handle_multi_select_removal(
            req, session, attrs, _gap_attr, _gap_to_remove,
            hiding_rules, rec_rules, con_rules,
        )
    # The block's own wording says "remove it" — a pronoun, not a named
    # option, so detect_multi_select_removal (which requires the option
    # to actually be named) never matches it. When the message still
    # carries a removal verb and there's exactly one unresolved gap
    # option, resolve "it" to that one unambiguous gap directly.
    if _cpq_engine._REMOVE_VERB_RE.search(req.question):
        _by_vn = {a.variable_name: a for a in attrs}
        _grid_links = _cpq_engine.resolve_array_grid_links(attrs)
        _gaps = [
            (selector_vn, item_value)
            for selector_vn, item_map in _grid_links.items()
            for item_value in (session.filled_multi.get(selector_vn) or [])
            if item_value.strip().lower() not in item_map
        ]
        _one_gap_attr = _by_vn.get(_gaps[0][0]) if len(_gaps) == 1 else None
        raven_log("DEBUG", "P4", "ask.removal.blocked_gap pronoun removal checked", context={
            "selected_option": "pronoun_gap_removal" if _one_gap_attr is not None else "continue",
            "available_options": _REMOVAL_OPTIONS,
            "reason_code": (
                "SINGLE_GAP" if _one_gap_attr is not None
                else "GAP_ATTR_MISSING" if len(_gaps) == 1
                else "NO_GAP" if not _gaps else "AMBIGUOUS_GAPS"),
            "gap_count": len(_gaps), "named_match": bool(_gap_removal_match),
            "target_field": getattr(_one_gap_attr, "variable_name", None),
            "turn": getattr(session, "turn", None)})
        if len(_gaps) == 1:
            _gap_selector_vn, _gap_item_value = _gaps[0]
            _gap_attr = _by_vn.get(_gap_selector_vn)
            if _gap_attr is not None:
                return _ask_handle_multi_select_removal_module._handle_multi_select_removal(
                    req, session, attrs, _gap_attr, [_gap_item_value],
                    hiding_rules, rec_rules, con_rules,
                )
    else:
        raven_log("DEBUG", "P4", "ask.removal.blocked_gap no removal request", context={
            "selected_option": "continue", "available_options": _REMOVAL_OPTIONS,
            "reason_code": "NAMED_REMOVAL_UNCONFIRMED" if _gap_removal_match else "NO_REMOVAL_VERB",
            "turn": getattr(session, "turn", None)})
    return None
