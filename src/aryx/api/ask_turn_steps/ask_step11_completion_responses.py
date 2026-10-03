"""Response builders for a turn with no attrs left pending — an
unresolved grid-quantity gap, a stale constraint re-ask, or genuine
configuration completion (STEP 6 FORMAT B) — split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). A selected grid option
with NO resolvable quantity attr at all (docs/CPQ_SESSION_2_OPEN_
ISSUES.md item 9) must never silently complete with a permanent per-row
gap. JSON is never shown unasked, even at completion (§6/Phase K) — this
branch only ever shows the verbose summary. Logic unchanged from the
original inline block. Every ask_api name below is read through the
module object (not imported by name) since tests patch several of them
by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_stale_constraint.ask_stale_constraint_reask import _reask_stale_constraint_violations

from aryx.api.ask_response_building.ask_cpq_summary_text import _cpq_summary_text
from aryx.raven_log import raven_log


def _step11_grid_gap_response(
    session: Any, visible_attrs: list, dropped_note: str,
) -> str | None:
    """Returns the answer text when a selected grid option has no
    resolvable quantity attr at all; None otherwise."""
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    unresolved_grid_gaps = _cpq_engine.unresolved_grid_quantity_options(
        visible_attrs, session.filled_multi)
    raven_log("DEBUG", "P4", "ask.response.grid_gap unresolved grid quantity check", context={
        "selected_option": "grid_gap_block" if unresolved_grid_gaps else "continue",
        "available_options": ["grid_gap_block", "continue"],
        "reason_code": "GRID_OPTION_NO_QUANTITY" if unresolved_grid_gaps else "NO_GRID_GAP",
        "gap_count": len(unresolved_grid_gaps or []),
        "gap_labels": [g[0] for g in (unresolved_grid_gaps or []) if g][:25],
        "turn": getattr(session, "turn", None)})
    if not unresolved_grid_gaps:
        return None
    session.status = "configuring"
    gap_list = "; ".join(f"**{val}** ({label})" for label, val in unresolved_grid_gaps)
    return (
        (f"{dropped_note.strip()}\n\n" if dropped_note else "")
        + f"⚠️ {gap_list} has no quantity field configured in this "
          f"catalog. Please remove it or choose a different option "
          f"before this configuration can be completed."
    )


def _step11_stale_reask_response(
    req: "Any", session: Any, attrs: list, con_rules: list, bml_eval: Any,
    catalog_prefix: str, dropped_note: str,
) -> str | None:
    """Returns the answer text when a stale constraint violation needs
    re-asking; None otherwise."""
    _stale_reask = _reask_stale_constraint_violations(
        session, attrs, con_rules, bml_eval, req.workspace_id, catalog_prefix,
    )
    raven_log("DEBUG", "P4", "ask.response.stale_reask stale constraint check", context={
        "selected_option": "continue" if _stale_reask is None else "stale_reask",
        "available_options": ["stale_reask", "continue"],
        "reason_code": "NO_STALE_VIOLATION" if _stale_reask is None else "STALE_CONSTRAINT_VIOLATION",
        "constraint_rule_count": len(con_rules or []),
        "turn": getattr(session, "turn", None)})
    if _stale_reask is None:
        return None
    return (f"{dropped_note.strip()}\n\n" if dropped_note else "") + _stale_reask


def _step11_completion_response(
    req: "Any", session: Any, attrs: list, display_filled: dict, rule_ids: set,
    dropped_note: str,
) -> str:
    """STEP 6 FORMAT B: verbose summary, JSON only on request. Always
    returns an answer — the final catch-all for a not-pending turn."""
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    session.status = "awaiting_approval"
    summary = _cpq_summary_text(
        display_filled, attrs, rule_ids,
        session.product_name, req.workspace_id, sources=session.filled_source,
        product_quantity=session.product_quantity, filled=session.filled,
        product_anchor_hint=session.product_anchor_question,
    )
    raven_log("DEBUG", "P4", "ask.response.completion configuration complete summary built", context={
        "selected_option": "completion_summary", "reason_code": "NOTHING_PENDING",
        "status": "awaiting_approval", "product_name": getattr(session, "product_name", None),
        "filled_count": len(display_filled or {}), "rule_governed_count": len(rule_ids or ()),
        "summary_len": len(summary or ""), "turn": getattr(session, "turn", None)})
    return (
        (f"{dropped_note.strip()}\n\n" if dropped_note else "")
        + f"Configuration complete for **{session.product_name}**.\n\n"
        + (f"{summary}\n\n" if summary else "")
        + f"Click **JSON** below to see the full payload, "
          f"say **confirm** to submit, or describe any changes."
    )
