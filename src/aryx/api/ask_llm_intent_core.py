"""Shared skeleton for every Tier-2 LLM intent fallback in ask_api.py,
split out of `api/ask_api.py` (Phase 6/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from
the original inline definition. `logger` is read through the ask_api
MODULE object (not imported by name) for consistency with the rest of
this decomposition, though it is not itself patched anywhere.
"""

from __future__ import annotations

import json
from typing import Any

from aryx import llm_runtime
from aryx.api import ask_api as _ask_api_module


def _llm_classify_intent_core(
    sys_prompt: str, user_prompt: str, workspace_id: int,
    validate: Any, role: str = "answer",
) -> Any:
    """Shared skeleton for every Tier-2 LLM intent fallback in this file.

    Factored out of `_llm_classify_change_intent` and
    `_llm_resolve_label_collision` (both pre-existing, both already
    following this exact shape): call the given tier's model, parse its
    JSON reply, and hand the parsed dict to a caller-supplied `validate`
    function that enforces the never-guess discipline specific to that
    call site (only real attrs/options ever get trusted). Any exception —
    LLM call failure, malformed JSON, missing braces — returns None rather
    than raising, since every caller here is a fallback that must never
    crash the turn.

    `role` — "answer" (default) uses `llm_runtime`'s reasoning-capable
    tier (backed by `llm_reason_model`) — despite the "answer" role name
    (`llm_runtime.chat`'s only two roles are "menial" and "answer"),
    it's genuinely the stronger model, needed for classifications that
    require real judgment rather than pattern matching (e.g.
    `_llm_classify_scope_reply` distinguishing "skip" vs "family_only"
    vs a specific candidate named indirectly). Pass role="menial" to opt
    a caller into the cheap/fast tier (`llm_menial_model`) instead, for
    a classification simple enough not to need it.
    """
    try:
        text, _it, _ot = llm_runtime.chat(role, sys_prompt, user_prompt, workspace_id=workspace_id)
        s, e = text.find("{"), text.rfind("}")
        parsed = json.loads(text[s:e + 1])
    except Exception as exc:  # noqa: BLE001 — fallback must never crash the turn
        _ask_api_module.logger.debug("llm intent core: llm call or parse failed: %r", exc)
        return None
    return validate(parsed)
