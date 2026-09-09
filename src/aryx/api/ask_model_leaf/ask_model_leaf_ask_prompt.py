"""Building the "which product line?" model-leaf disambiguation prompt,
split out of `_run_cpq_turn_inner`'s model-leaf disambiguation block
(Phase 10/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md) purely to keep the sibling `ask_model_leaf_
resolve.py` under the line cap. Logic unchanged from the original
inline block. `_compose_disambiguation_question` and `_persist_cpq_
history` are read through the ask_api MODULE object (not imported by
name) since ask_api tests patch several of its own module-level names
by dotted path, and the former is not yet split out of ask_api.py.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_label_collision_detect_and_compose import _compose_disambiguation_question
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.cpq.pending_scope import set_pending_scope


def _build_model_leaf_ask_prompt(
    req: "Any", session: Any, leaf_candidates: list,
) -> dict[str, Any]:
    session.pending_model_leaf_candidates = leaf_candidates
    set_pending_scope(
        session,
        kind="family_disambiguation",
        candidates=list(leaf_candidates),
        origin_question=req.question,
        attr_vn="",
        asked_turn=session.turn,
    )
    _leaf_lines = "\n".join(f"{i+1}. {leaf}" for i, leaf in enumerate(leaf_candidates))
    _static_leaf_answer = (
        f"This family has more than one product line — which one are "
        f"you configuring?\n\n{_leaf_lines}"
    )
    _leaf_answer = _compose_disambiguation_question(
        req.question, "which specific product line/model they want",
        leaf_candidates,
        {"Country": session.country, "Product": session.product_name},
        _static_leaf_answer, req.workspace_id,
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, _leaf_answer)
    return {
        "answer": _leaf_answer, "terms": [],
        "tools_called": ["cpq_model_leaf_ambiguous()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
