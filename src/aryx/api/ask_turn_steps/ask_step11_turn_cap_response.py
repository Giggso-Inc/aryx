"""Turn-cap-reached response builder, split out of `_run_cpq_turn_inner`
(Phase 10/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). Turn cap reached with attrs still unresolved —
NEVER fabricate a complete BOM here: a payload presented as final must
not contain guessed values. Emits an explicitly-incomplete state and
keeps the guided flow open on the next pending attribute. Logic
unchanged from the original inline block. Every ask_api name below is
read through the module object (not imported by name) since tests patch
several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_label_collision.ask_label_collision_detect_and_compose import _label_collision_for
from aryx.api.ask_label_collision.ask_label_collision_prompt_and_narrow import _label_collision_prompt


def _step11_turn_cap_response(
    req: "Any", session: Any, visible_attrs: list, pending: list,
    constrained_opts: dict, validation_rules: list,
) -> str:
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    unresolved = [a.display_label for a in pending]
    next_attr = pending[0]
    _pending_collision = _label_collision_for(next_attr, visible_attrs, session, pending)
    if _pending_collision:
        session.pending_label_collision_vns = [a.variable_name for a in _pending_collision]
        q_block = _label_collision_prompt(
            _pending_collision, session, req.question, req.workspace_id)
    else:
        q_block = _cpq_engine.next_question_prompt(
            next_attr, "", constrained_opts.get(next_attr.entity_id),
            validation_rules=validation_rules, attrs=visible_attrs,
        )
    return (
        f"⚠️ The configuration for **{session.product_name}** is "
        f"**incomplete** — {len(unresolved)} attribute(s) still need "
        f"your input: *{', '.join(unresolved[:8])}"
        f"{'…' if len(unresolved) > 8 else ''}*.\n\n"
        f"I won't generate a BOM with guessed values. Let's continue:"
        f"\n\n{q_block}"
    )
