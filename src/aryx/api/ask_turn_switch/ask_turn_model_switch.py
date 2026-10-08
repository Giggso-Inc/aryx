"""Offering and answering a model switch inside one product family.

`_offer_model_switch` runs inside `_handle_cascade` (the shared single-change
handler) when the change targets the Product (model) answer and
`cpq_model_switch_snapshot_enabled` is on. Instead of wiping Product and its
dependents straight away, it asks the user to confirm. A message that changes
the model together with other answers goes through `_offer_model_switch_in_batch`
(from `_handle_cascade_multi` and the compound-split path): the model question
is asked on its own and the other changes wait, so they never land on the old
model. `_handle_confirm_model_switch_anchor` reads the next turn's reply and
completes the switch via `_complete_model_switch`, declines, or hands a reply
that names something else back to the normal turn (which re-offers if it names
another model).
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
_YES_RE = re.compile(
    r"^\s*(y|yes|yeah|yep|ok|okay|sure|alright|switch|confirm|go\s+ahead|do\s+it)\b", re.IGNORECASE)
_NO_RE = re.compile(r"^\s*(n|no|nope|nah|never|not\s+now|not\s+really)\b", re.IGNORECASE)
# A negation or contrast anywhere in the reply ("NOT APX 900", "I don't want
# APX 900", "keep APX 3000, not APX 900", "switch to X instead").
_NEGATION_RE = re.compile(
    r"\b(no|not|never|don'?t|doesn'?t|won'?t|rather|than|instead|keep|stay|forget|cancel)\b|n't\b",
    re.IGNORECASE)
# Words that add nothing on their own ("yes please", "no thanks, keep it").
_FILLER = frozenset({
    "please", "thanks", "thank", "you", "ok", "okay", "sure", "go", "ahead", "do", "it",
    "switch", "confirm", "current", "one", "the", "that", "this", "fine", "alright",
    "no", "not", "never", "don", "doesn", "won", "t", "rather", "than", "instead",
    "keep", "stay", "forget", "cancel", "want", "i", "to",
})
_OFFER_OPTIONS = ["offer_model_switch", "flag_off", "not_model_attr", "no_new_model"]
_REPLY_OPTIONS = ["switch", "stay", "hand_back"]
_BATCH_NOTE = (
    "\n\nThe other changes in your message have not been applied yet. "
    "Send them again after you answer, so they go on the right model."
)


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
    req: Any, session: Any, attrs: list, changed_attr: Any, new_value_hint: str, note: str = "",
) -> dict[str, Any] | None:
    """Ask to confirm a change of the Product answer; None to run the cascade.

    Args:
        req: The ask request (question, workspace_id).
        session: The live CpqSession; gets the pending model-switch fields.
        attrs: The catalog's config attributes (unused, kept for call symmetry).
        changed_attr: The attribute the change request targets.
        new_value_hint: The wording that names the new value.
        note: Extra text appended to the question (used for batched changes).

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
        "target_model": match[0], "batched": bool(note),
        "has_snapshot": match[0] in session.model_snapshots,
        "turn": getattr(session, "turn", None)})
    answer = (
        f"This quote is for **{current_display}**. Switch to **{match[1]}**? "
        f"Your {current_display} answers will be saved, and you can switch back later. (yes/no)"
        f"{note}"
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return _cpq_response(session, answer, "cpq_model_switch_candidate()")


def _offer_model_switch_in_batch(
    req: Any, session: Any, attrs: list, changes: list,
) -> dict[str, Any] | None:
    """Offer the model switch alone when a batch of changes includes Product.

    Args:
        req: The ask request for the whole message.
        session: The live CpqSession.
        attrs: The catalog's config attributes.
        changes: (attribute, value_hint) pairs named in one message.

    Returns:
        The confirmation response (the other changes are not applied), or None
        when no change in the batch is a model switch.
    """
    model_change = next((c for c in changes if c[0].variable_name == PRODUCT_LITERAL), None)
    if model_change is None or len(changes) < 2:
        return None
    offer = _offer_model_switch(req, session, attrs, model_change[0], model_change[1], note=_BATCH_NOTE)
    raven_log("DEBUG", "P4", "ask.model_switch.batch model change inside a multi-change message", context={
        "selected_option": "offer_alone" if offer is not None else "apply_all",
        "available_options": ["offer_alone", "apply_all"],
        "reason_code": "MODEL_SWITCH_OFFERED" if offer is not None else "NOT_A_MODEL_SWITCH",
        "change_count": len(changes), "turn": getattr(session, "turn", None)})
    return offer


def _names_model(reply: str, model_display: str) -> bool:
    """Return True when whole words of the reply spell the model's name."""
    target = _norm(model_display)
    words = re.findall(r"[a-z0-9]+", (reply or "").lower())
    return bool(target) and any(
        "".join(words[i:j]) == target
        for i in range(len(words)) for j in range(i + 1, len(words) + 1)
    )


def _reply_rest(reply: str, head: "re.Match[str] | None") -> list[str]:
    """Return the words after a yes/no head, minus filler words."""
    tail = reply[head.end():] if head else reply
    return [w for w in re.findall(r"[a-z0-9]+", tail.lower()) if w not in _FILLER]


def _classify_reply(reply: str, target_display: str) -> tuple[str, str]:
    """Decide what a reply to the switch question means, without the LLM.

    Returns:
        (decision, reason_code). decision is "switch", "stay", "hand_back"
        (the reply carries its own request for the normal turn), "llm" (ask
        the classifier; not-accept hands back) or "llm_or_stay" (the reply
        names the offered model but with a negation; not-accept stays).
    """
    yes_head, no_head = _YES_RE.match(reply), _NO_RE.match(reply)
    negated = bool(no_head or _NEGATION_RE.search(reply))
    rest = _reply_rest(reply, yes_head or no_head)
    if _names_model(reply, target_display):
        # "NOT APX 900", "keep APX 3000, not APX 900": never a plain yes.
        return ("llm_or_stay", "NEGATED_OFFERED_MODEL") if negated else ("switch", "NAMES_OFFERED_MODEL")
    if negated:
        return ("stay", "CLEAR_NO") if not rest else ("hand_back", "REPLY_NAMES_SOMETHING_ELSE")
    if yes_head:
        # "yes and also add GPS": switch, the rest carries on through the turn.
        return ("switch", "CLEAR_YES") if not rest else ("switch", "YES_WITH_MORE")
    return "llm", "UNCLEAR_REPLY"


def _handle_confirm_model_switch_anchor(req: Any, session: Any) -> dict[str, Any] | None:
    """Read the reply to the switch question and act on it.

    Args:
        req: The ask request whose question is the reply to the confirm prompt.
        session: The live CpqSession with `pending_model_switch` set.

    Returns:
        None when the switch completed or the reply is handed back to the
        normal turn (it names something else); the "no changes made"
        response when the user declined.
    """
    target_display = session.pending_model_switch_display or session.pending_model_switch
    current_display = (
        session.display_filled.get(PRODUCT_LITERAL, "") or session.filled.get(PRODUCT_LITERAL, ""))
    reply = req.question or ""
    decision, reason = _classify_reply(reply, target_display)
    llm_consulted = decision in ("llm", "llm_or_stay")
    if llm_consulted:
        accepted = _llm_classify_switch_reply(
            reply, target_display, current_display, req.workspace_id) == "accept"
        fallback = "stay" if decision == "llm_or_stay" else "hand_back"
        decision, reason = ("switch", "LLM_ACCEPT") if accepted else (fallback, "LLM_NOT_ACCEPT")
    raven_log("DEBUG", "P4", "ask.model_switch.confirm_reply model switch reply classified", context={
        "selected_option": decision, "available_options": _REPLY_OPTIONS,
        "reason_code": reason, "llm_consulted": llm_consulted,
        "reply_len": len(reply), "turn": getattr(session, "turn", None),
        "target_model": session.pending_model_switch})
    if decision == "switch":
        _complete_model_switch(session, session.pending_model_switch, target_display, req.workspace_id)
        return None
    session.pending_model_switch = ""
    session.pending_model_switch_display = ""
    session.pending_anchor = ""
    if decision == "hand_back":
        # The reply carries its own request ("no, APX 8000", "switch to X
        # instead"): the normal turn handles it and re-offers if it names
        # another model.
        return None
    answer = f"No changes made — the quote stays on **{current_display}**."
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return _cpq_response(session, answer, "cpq_model_switch_declined()")
