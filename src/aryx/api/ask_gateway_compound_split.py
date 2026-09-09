"""Attempting an LLM-first compound-message split before falling to the
generic gateway clarify prompt, split out of `_llm_first_gateway_turn`
(Phase 7/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md) purely to keep the sibling `ask_handle_llm_first_
gateway_turn.py` under the line cap. Logic unchanged from the original
inline block. `_cpq_engine`, `_handle_cpq_qa`, and `_persist_cpq_history`
are read through the ask_api MODULE object (not imported by name) since
these are patched by ask_api tests and/or not yet split out of ask_api.py.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_attr_text_helpers import _resolve_split_change_text
from aryx.api.ask_llm.ask_llm_switch_reply_and_compound_split import _llm_split_compound_change_and_question
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_handle import ask_handle_cpq_qa as _ask_handle_cpq_qa_module
from aryx.api.ask_handle.ask_handle_cascade import _handle_cascade
from aryx.api.ask_llm.ask_llm_split_multi_attr_change import _llm_split_multi_attr_change_request


def _try_compound_split_on_clarify(
    req: "Any", session: Any, attrs: list,
    hiding_rules: list, rec_rules: list, con_rules: list, reader: Any,
) -> dict[str, Any] | None:
    """Compound "change X and what is Y" messages (docs/CPQ_COMPOUND_
    CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §4) land as an ambiguous clarify
    — the gateway's own schema can't hold two targets. Try an LLM-first
    split BEFORE falling to the generic clarify prompt; cheap conjunction
    pre-check keeps this from firing on ordinary ambiguous single-intent
    messages that have no "and"/";" at all.

    docs/config_consistency_issues_2026-07-30.md Issue 12 follow-up —
    live-confirmed a THIRD phrasing this conjunction-only gate still
    misses entirely: a "-"-separated compound with no "and"/";" anywhere.
    A keyword-only gate can never anticipate every way a customer
    separates two requests; `last_qa_variables` already knows — cheaply,
    without any extra LLM call — that the immediately preceding turn
    discussed exactly these 2+ attributes, so it's an equally valid (and
    keyword-free) signal that a split is worth attempting.

    Returns None when no compound split applies (or a split's fragments
    didn't resolve deterministically) — caller falls through to the
    existing clarify path unchanged, same never-guess discipline as
    every other Tier-2 fallback in this file.
    """
    from aryx.api import ask_api as _ask_api_module
    _cq_lower = req.question.lower()
    _looks_compound = " and " in _cq_lower or ";" in req.question
    _recent_multi_topic = len(session.last_qa_variables or []) >= 2
    if not (_looks_compound or _recent_multi_topic):
        return None
    _split = _llm_split_compound_change_and_question(
        req.question, req.workspace_id,
    )
    if _split is not None:
        _change_text, _question_text = _split
        _change_hint = _ask_api_module._cpq_engine.detect_change_request(
            _change_text, attrs, session.filled, session.filled_multi,
        )
        if _change_hint is not None:
            _changed_attr, _new_value_hint = _change_hint
            _change_req = req.model_copy(update={"question": _change_text})
            _change_result = _handle_cascade(
                _change_req, session, attrs, _changed_attr,
                _new_value_hint, hiding_rules, rec_rules, con_rules,
            )
            _qa_req = req.model_copy(update={"question": _question_text})
            _qa_result = _ask_handle_cpq_qa_module._handle_cpq_qa(_qa_req, session, attrs, reader)
            _combined = (
                f"{_change_result.get('answer', '')}\n\n"
                f"{_qa_result.get('answer', '')}"
            )
            _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, _combined)
            return {
                **_qa_result,
                "answer": _combined,
                "tools_called": (
                    list(_change_result.get("tools_called") or [])
                    + list(_qa_result.get("tools_called") or [])
                ),
            }
        # Split succeeded but the change clause didn't resolve
        # deterministically — fall through to the existing clarify path.
        return None
    # Not a change+question compound — try change+change
    # (docs/config_consistency_issues_2026-07-30.md Issue 12):
    # classify_intent's schema can only ever name ONE target, so a
    # two-target compound collapses to "ambiguous" here regardless of
    # how well-formed it is. last_qa_variables (both attrs from the
    # customer's immediately preceding compound options query) is
    # passed in as context to help produce a correct split.
    _multi_change_texts = _llm_split_multi_attr_change_request(
        req.question, attrs, req.workspace_id,
        last_qa_variables=session.last_qa_variables,
    )
    if not _multi_change_texts:
        return None
    _resolved_changes = [
        (
            _mc_text,
            _resolve_split_change_text(
                _mc_text, attrs, session.filled, session.filled_multi,
                last_qa_variables=session.last_qa_variables,
            ),
        )
        for _mc_text in _multi_change_texts
    ]
    # Never half-apply and guess (same discipline as the change+question
    # split above) — only proceed when EVERY split fragment resolved to
    # a real attr+value; otherwise fall through to the existing clarify
    # path unchanged.
    if not all(hint is not None for _, hint in _resolved_changes):
        return None
    _mc_results = []
    for _mc_text, _mc_hint in _resolved_changes:
        _mc_attr, _mc_value_hint = _mc_hint
        _mc_req = req.model_copy(update={"question": _mc_text})
        _mc_results.append(_handle_cascade(
            _mc_req, session, attrs, _mc_attr,
            _mc_value_hint, hiding_rules, rec_rules, con_rules,
        ))
    _combined = "\n\n".join(r.get("answer", "") for r in _mc_results)
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, _combined)
    return {
        **_mc_results[-1],
        "answer": _combined,
        "tools_called": [
            t for r in _mc_results for t in (r.get("tools_called") or [])
        ],
    }
