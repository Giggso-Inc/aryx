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

from aryx.api.ask_stale_constraint_reask import _reask_stale_constraint_violations

from aryx.api.ask_response_building.ask_cpq_summary_text import _cpq_summary_text


def _step11_grid_gap_response(
    session: Any, visible_attrs: list, dropped_note: str,
) -> str | None:
    """Returns the answer text when a selected grid option has no
    resolvable quantity attr at all; None otherwise."""
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    unresolved_grid_gaps = _cpq_engine.unresolved_grid_quantity_options(
        visible_attrs, session.filled_multi)
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
    )
    return (
        (f"{dropped_note.strip()}\n\n" if dropped_note else "")
        + f"Configuration complete for **{session.product_name}**.\n\n"
        + (f"{summary}\n\n" if summary else "")
        + f"Click **JSON** below to see the full payload, "
          f"say **confirm** to submit, or describe any changes."
    )
