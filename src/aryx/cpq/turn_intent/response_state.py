"""Simple turn-state detectors (Phase 4 step 2 extraction from
``cpq/engine.py`` -- see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md):
explicit response-mode/approval/decline/summary-request/Q&A detection.
None of these need engine-instance callback.
"""

from __future__ import annotations

from aryx.cpq.state import ConfigAttr
from aryx.cpq.turn_intent.patterns import _APPROVAL_RE, _BATCH_REQUEST_RE, _JSON_REQUEST_RE, _QA_INTENT_RE
from aryx.cpq.turn_intent.patterns2 import _DECLINE_RE, _SHOW_SUMMARY_RE


def detect_response_mode_request(question: str) -> str | None:
    """Return "json" | "batch" | None for an explicit presentation request.

    CPQ_CASCADE_CONVERSATION_PLAN.md §6: the client gets the rich default
    (verbose narrative, one question at a time) unless they explicitly
    ask for the JSON payload or the full batch of pending questions.
    """
    if _JSON_REQUEST_RE.search(question):
        return "json"
    if _BATCH_REQUEST_RE.search(question):
        return "batch"
    return None

def detect_approval(question: str) -> bool:
    """True when the user is approving/confirming the configuration (Step 8)."""
    return bool(_APPROVAL_RE.search(question.strip()))

def detect_decline(question: str) -> bool:
    """True when the user is explicitly rejecting the awaiting-approval
    configuration (Step 8 rejection). See ISSUE-002 fix plan for the
    production bug this closes: an explicit "no, decline that" was being
    misdispatched as an approval because no deterministic decline
    detector existed at all.
    """
    return bool(_DECLINE_RE.search(question.strip()))

def detect_show_summary_request(question: str) -> bool:
    """True when the customer is asking to see the configuration
    summary again, not naming a specific attribute or approving.
    """
    return bool(_SHOW_SUMMARY_RE.search(question.strip()))

def detect_qa_question(
    question: str,
    pending_attr: "ConfigAttr | None" = None,
    strict: bool = False,
) -> bool:
    """True when the user is asking a Q&A question rather than answering a config prompt.

    strict=True — only fires on explicit `?` or Q&A intent keywords. Use during
    active configuration to avoid intercepting free-text config answers.
    strict=False (default) — also fires when a long message doesn't match any
    option for the pending attr. Use during awaiting_approval review.
    """
    q = question.strip()
    if "?" in q:
        return True
    if _QA_INTENT_RE.search(q):
        return True
    if strict:
        return False
    # Awaiting-approval heuristic: long message that matches no visible option → Q&A
    if pending_attr and pending_attr.options and len(q.split()) > 5:
        q_lower = q.lower()
        if not any(
            o.item_value.lower() in q_lower or o.display_name.lower() in q_lower
            for o in pending_attr.options
        ):
            return True
    return False
