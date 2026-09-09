"""Conversational orphan-question invariant (post-turn guardrail).

Split out of `cpq/session_guard.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_QUESTION_RE = re.compile(
    r"(?is)"
    r"(?:"
    r"which\s+(?:value|attribute|field|one|product|country|hardware|"
    r"option|service|catalog|model)\b"
    r"|what\s+(?:value|would you like|is the|are the options)\b"
    r"|did you mean\b"
    r"|which one did you mean\b"
    r"|reply with (?:the )?(?:name|number|value)\b"
    r"|pick a number\b"
    r"|please\s+(?:name|pick|choose|say|provide|confirm|select)\b"
    r"|destination country\b.*\?"
    r"|switch to\b.*\?"
    r"|discard the current configuration\b"
    r")",
)


def answer_is_config_question(answer: str) -> bool:
    """True when the answer is soliciting a config/attribute/anchor reply."""
    if not answer or "?" not in answer:
        return False
    tail = answer.strip()[-600:]
    if "?" not in tail:
        return False
    return bool(_CONFIG_QUESTION_RE.search(tail))


def has_consumable_pending_state(session_data: dict[str, Any] | None) -> bool:
    """True when session_data has pending state that can absorb the next reply."""
    if not session_data:
        return False
    if session_data.get("pending_variables"):
        return True
    if session_data.get("pending_anchor"):
        return True
    if session_data.get("pending_change_collision_vns"):
        return True
    if session_data.get("pending_label_collision_vns"):
        return True
    if session_data.get("pending_change_no_value_vn"):
        return True
    if session_data.get("pending_clarify_vns"):
        return True
    if session_data.get("pending_switch_product") or session_data.get(
        "pending_switch_question",
    ):
        return True
    if session_data.get("pending_switch_candidates"):
        return True
    if session_data.get("pending_model_leaf_candidates"):
        return True
    if session_data.get("pending_intent_queue"):
        return True
    if session_data.get("pending_multi_intent_vn"):
        return True
    # PROMPT 7: constrained option / family / "did you mean" lists
    if session_data.get("pending_scope_candidates"):
        return True
    return False


def assert_conversational_invariant(
    answer: str,
    session_data: dict[str, Any] | None,
    *,
    run_id: str = "",
    log: bool = True,
) -> list[str]:
    """Post-turn guardrail: config-seeking questions need consumable pending."""
    violations: list[str] = []
    if not answer_is_config_question(answer):
        return violations
    if has_consumable_pending_state(session_data):
        return violations
    rid = run_id or (session_data or {}).get("run_id") or "-"
    msg = (
        f"cpq_orphan_question run_id={rid}: answer asks a config question "
        f"but session has no consumable pending state "
        f"(pending_variables/anchor/collision/clarify/switch/no_value/…)"
    )
    violations.append(msg)
    if log:
        logger.warning("%s | answer_tail=%r", msg, (answer or "")[-180:])
    return violations


def enforce_conversational_invariant(result: dict[str, Any]) -> dict[str, Any]:
    """Attach invariant check onto a CPQ response dict."""
    if not isinstance(result, dict):
        return result
    answer = result.get("answer") or ""
    session_data = result.get("session_data") or {}
    rid = ""
    if isinstance(session_data, dict):
        rid = str(session_data.get("run_id") or "")
    violations = assert_conversational_invariant(
        answer, session_data if isinstance(session_data, dict) else None,
        run_id=rid, log=True,
    )
    if violations:
        result["_cpq_invariant_violations"] = list(violations)
    else:
        result.pop("_cpq_invariant_violations", None)
    return result
