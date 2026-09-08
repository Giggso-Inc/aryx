"""Combined deterministic+LLM decline detection, and the label-collision
LLM fallback, split out of `ask_api.py` (final sweep, Phase 11/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
`_LOOSE_DECLINE_HINT_RE` is a cheap pre-filter gating the LLM fallback —
NOT itself a decline decision (live regression caught during this fix:
without a gate, an LLM call fired on essentially every cascade turn in
the whole system, not just plausible declines). `_llm_resolve_label_
collision` is classify-only over a FIXED, already-known candidate list,
tried only after the deterministic check (exact variable_name or
1-based list index) finds nothing. Logic unchanged from the original
inline definitions. `_llm_detect_change_decline`, `_llm_classify_
intent_core`, and `logger` are read through the ask_api module object
(not imported by name) since tests patch several ask_api names by
dotted path.
"""

from __future__ import annotations

import re
from typing import Any

from aryx.api.ask_llm_intent_core import _llm_classify_intent_core
from aryx.api.ask_llm_topic_switch_and_change_decline import _llm_detect_change_decline

# Cheap pre-filter, gating the LLM fallback below — NOT itself a
# decline decision. Live regression caught during this fix: without a
# gate, `_is_decline_reply` tried the LLM on the "no strict-regex
# match" branch of `_handle_cascade`, which is the SAME branch every
# ordinary value change ("change solution type to CloudRC") falls
# through — that made an LLM call on essentially every cascade turn in
# the whole system, not just plausible declines. This loose word list
# only has to be broad enough to contain every decline phrasing the
# strict regexes miss ("nah, forget it" / "on second thought don't
# bother"), not exact — the LLM call itself still does the real
# decision, this only decides whether it's even worth asking.
_LOOSE_DECLINE_HINT_RE = re.compile(
    r"\b(no|not|don'?t|never|forget|skip|leave|keep|cancel|nah|meh|"
    r"nevermind|bother|actually|mind)\b",
    re.IGNORECASE,
)


def _is_decline_reply(
    question: str, attr_label: str, current_value: str, workspace_id: int,
    *, deterministic_hit: bool,
) -> bool:
    """Combines a deterministic decline-regex result (passed in by the
    caller, since the two call sites use two different regexes) with the
    narrow LLM fallback. Deterministic hit short-circuits before any LLM
    call. `_LOOSE_DECLINE_HINT_RE` gates the LLM call itself — an
    ordinary value change never contains any of these words and never
    reaches the LLM at all.
    """
    if deterministic_hit:
        return True
    if not _LOOSE_DECLINE_HINT_RE.search(question):
        return False
    return _llm_detect_change_decline(question, attr_label, current_value, workspace_id)


def _llm_resolve_label_collision(
    reply: str, candidates: list, session: Any, workspace_id: int,
) -> str | None:
    """LLM fallback for resolving a label-collision reply, tried only
    after the deterministic check (exact variable_name or 1-based list
    index) finds nothing. Includes each candidate's CURRENT value so a
    reply like "the one that currently has jacket magnetic mount" can
    resolve correctly.
    """
    from aryx.api import ask_api as _ask_api_module
    logger = _ask_api_module.logger
    catalog_lines = [
        f"- {a.variable_name} [{a.select_type}] ({a.display_label}): "
        f"current={session.filled_multi.get(a.variable_name) or session.display_filled.get(a.variable_name)!r}"
        for a in candidates
    ]
    sys = (
        "You resolve which of several similarly-labeled attributes a user "
        "meant, from their reply to a disambiguation prompt. Only use "
        "variable_names from the list given — never invent one. If the "
        "reply doesn't clearly point to exactly one, say none."
    )
    user = (
        "CANDIDATES (variable_name [select_type] (label): current=...):\n"
        + "\n".join(catalog_lines)
        + f"\n\nUSER REPLY: {reply}\n\n"
        'Reply ONLY as JSON: {"variable_name": "<exact name from list, or empty>"}'
    )
    valid_vns = {a.variable_name for a in candidates}

    def _validate(parsed: dict) -> str | None:
        vn = parsed.get("variable_name") or ""
        if vn not in valid_vns:
            logger.debug("llm label-collision fallback: model named vn %r not in candidates %r",
                          vn, valid_vns)
            return None
        return vn

    return _llm_classify_intent_core(sys, user, workspace_id, _validate)
