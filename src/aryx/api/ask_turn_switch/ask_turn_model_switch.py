"""Offering and answering a model switch inside one product family.

`_offer_model_switch` runs inside `_handle_cascade` (the shared single-change
handler every change path goes through) when the change targets the Product
(model) answer and `cpq_model_switch_snapshot_enabled` is on. Instead of
wiping Product and its dependents straight away, it asks the user to confirm.
`_handle_confirm_model_switch_anchor` reads the next turn's yes/no reply with the
same rules as the family switch (regex first, LLM only for unclear replies) and
completes the switch via `_complete_model_switch`, or keeps the current model.

ponytail: only the single-change path (`_handle_cascade`) is gated; a message
naming Product together with other changes (`_handle_cascade_multi`) still runs
today's cascade. Gate that path too if multi-change model switches show up.
"""

from __future__ import annotations

import re
from typing import Any

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_llm.ask_llm_switch_reply_and_compound_split import _llm_classify_switch_reply
from aryx.api.ask_scope_and_pending.ask_change_decline_and_scope_memory import _extract_replacement_clause
from aryx.api.ask_turn_switch.ask_turn_model_switch_complete import _complete_model_switch
from aryx.config import get_settings
from aryx.cpq.catalog_profile import PRODUCT_LITERAL
from aryx.raven_log import raven_log

CONFIRM_MODEL_SWITCH_ANCHOR = "confirm_model_switch"
_YES_RE = re.compile(r"^\s*(y|yes|switch|confirm)\b", re.IGNORECASE)
_NO_RE = re.compile(r"^\s*(n|no|nope|nah|never|not\s+now|not\s+really)\b", re.IGNORECASE)
_OFFER_OPTIONS = ["offer_model_switch", "flag_off", "not_model_attr", "no_new_model"]


def _norm(text: str) -> str:
    """Lower-case and strip everything but letters and digits."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _cpq_response(session: Any, answer: str, tool: str) -> dict[str, Any]:
    """Build the standard engine-only turn response."""
    return {
        "answer": answer, "terms": [], "tools_called": [tool],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }


def _log_offer(reason: str, selected: str, session: Any) -> None:
    """Record the offer decision for this change."""
    raven_log("DEBUG", "P4", "ask.model_switch.offer model switch offer decided", context={
        "selected_option": selected, "available_options": _OFFER_OPTIONS,
        "reason_code": reason, "turn": getattr(session, "turn", None),
        "current_model": session.filled.get(PRODUCT_LITERAL, "")})


def _offer_model_switch(
    req: Any, session: Any, attrs: list, changed_attr: Any, new_value_hint: str,
) -> dict[str, Any] | None:
    """Ask to confirm a change of the Product answer; None to run the cascade.

    Args:
        req: The ask request (question, workspace_id).
        session: The live CpqSession; gets the pending model-switch fields.
        attrs: The catalog's config attributes (unused, kept for call symmetry).
        changed_attr: The attribute the change request targets.
        new_value_hint: The wording that names the new value.

    Returns:
        The confirmation response, or None when this change is not a model
        switch (flag off, another attribute, or no different model matched).
    """
    from aryx.api import ask_api as _ask_api_module
    if not get_settings().cpq_model_switch_snapshot_enabled:
        _log_offer("FLAG_OFF", "flag_off", session)
        return None
    if changed_attr.variable_name != PRODUCT_LITERAL or changed_attr.select_type == "multi":
        _log_offer("CHANGED_ATTR_NOT_MODEL", "not_model_attr", session)
        return None
    current = session.filled.get(PRODUCT_LITERAL, "")
    wanted_clause, _rejected = _extract_replacement_clause(new_value_hint)
    match = _ask_api_module._cpq_engine.apply_answer(changed_attr, wanted_clause or new_value_hint)
    if not current or not match or match[0] == current:
        _log_offer("NO_DIFFERENT_MODEL_MATCHED", "no_new_model", session)
        return None
    session.pending_model_switch, session.pending_model_switch_display = match[0], match[1]
    session.pending_anchor = CONFIRM_MODEL_SWITCH_ANCHOR
    current_display = session.display_filled.get(PRODUCT_LITERAL, "") or current
    raven_log("INFO", "P4", "ask.model_switch.offered model change needs confirmation", context={
        "selected_option": "offer_model_switch", "available_options": _OFFER_OPTIONS,
        "reason_code": "MODEL_ANSWER_CHANGED", "current_model": current,
        "target_model": match[0],
        "has_snapshot": match[0] in session.model_snapshots,
        "turn": getattr(session, "turn", None)})
    answer = (
        f"This quote is for **{current_display}**. Switch to **{match[1]}**? "
        f"Your {current_display} answers will be saved, and you can switch back later. (yes/no)"
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return _cpq_response(session, answer, "cpq_model_switch_candidate()")


def _handle_confirm_model_switch_anchor(req: Any, session: Any) -> dict[str, Any] | None:
    """Read the yes/no reply; None after switching so the turn continues.

    Args:
        req: The ask request whose question is the reply to the confirm prompt.
        session: The live CpqSession with `pending_model_switch` set.

    Returns:
        None when the switch completed (the caller continues the turn), or the
        "no changes made" response when the user declined.
    """
    target_display = session.pending_model_switch_display or session.pending_model_switch
    current_display = (
        session.display_filled.get(PRODUCT_LITERAL, "") or session.filled.get(PRODUCT_LITERAL, ""))
    reply = req.question or ""
    deterministic_yes = bool(_YES_RE.match(reply)) or (
        bool(_norm(target_display)) and _norm(reply) == _norm(target_display))
    clear_no = bool(_NO_RE.match(reply))
    affirmative = deterministic_yes
    if not deterministic_yes and not clear_no:
        affirmative = _llm_classify_switch_reply(
            reply, target_display, current_display, req.workspace_id) == "accept"
    raven_log("DEBUG", "P4", "ask.model_switch.confirm_reply model switch reply classified", context={
        "selected_option": "switch" if affirmative else "stay",
        "available_options": ["switch", "stay"],
        "reason_code": (
            "DETERMINISTIC_AFFIRMATIVE" if deterministic_yes
            else "CLEAR_DECLINE" if clear_no
            else "LLM_ACCEPT" if affirmative else "LLM_NOT_ACCEPT"),
        "llm_consulted": not deterministic_yes and not clear_no,
        "reply_len": len(reply), "turn": getattr(session, "turn", None),
        "target_model": session.pending_model_switch})
    if affirmative:
        _complete_model_switch(session, session.pending_model_switch, target_display)
        return None
    session.pending_model_switch = ""
    session.pending_model_switch_display = ""
    session.pending_anchor = ""
    answer = f"No changes made — the quote stays on **{current_display}**."
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return _cpq_response(session, answer, "cpq_model_switch_declined()")
