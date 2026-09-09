"""Proactive stale-constraint recheck run at the exact point a
"Configuration complete" response is about to be shown, split out of
`api/ask_api.py` (Phase 4/11-phase ask_api decomposition, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md). The three named stages
(`ask_stale_constraint_conflicted.py`, `ask_stale_constraint_silent_
resolve.py`, `ask_stale_constraint_prompt.py`) were split out purely to
keep this file under the line cap. Logic unchanged from the original
inline body. `_cpq_engine` is read through the ask_api MODULE object
(not imported by name) since at least one test replaces the whole
singleton via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

import logging
from typing import Any

from aryx.api.ask_data_table_conflict_reask import _reask_confirmed_data_table_conflict
from aryx.api.ask_stale_constraint.ask_stale_constraint_conflicted import handle_conflicted_violations
from aryx.api.ask_stale_constraint.ask_stale_constraint_prompt import build_stale_reask_prompt
from aryx.api.ask_stale_constraint.ask_stale_constraint_silent_resolve import silently_reresolve_hard_excluded
from aryx.cpq.bom_gate import find_missing_required_fields, recheck_constraints

logger = logging.getLogger(__name__)


def _reask_stale_constraint_violations(
    session: Any, attrs: list, con_rules: list, bml_eval: Any,
    workspace_id: int | None = None, catalog_prefix: str = "",
) -> str | None:
    """Proactively runs the same stale-constraint recheck the confirm-time
    BOM gate performs (bom_gate.recheck_constraints) at the exact point a
    "Configuration complete" response is about to be shown, so a config is
    never announced complete while holding a value a currently-active
    constraint has already ruled out — the customer is asked to fix it one
    turn EARLIER, instead of being told "complete" and only finding out at
    confirm (docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §4.1 explicitly
    deferred exactly this — "surfacing it to the user directly is a
    separate, not-yet-built follow-up" — this is that follow-up, reusing
    the exact same auto-clear-and-reask mechanism confirm's own gate
    already trusts, rather than inventing a second one).

    Mutates `session` (pops the stale value(s), sets pending_variables,
    status="configuring", complete=False) exactly like the confirm-time
    gate's own stale-violation handling, and returns the next-question
    prompt text to show instead of "Configuration complete" — or None if
    nothing is stale, in which case the caller proceeds with its normal
    "show complete" branch unchanged. A recheck failure degrades to None
    (never blocks a turn on this proactive, best-effort check — the
    confirm-time gate is still the authoritative, hard backstop).

    Also checks (2026-08-08) for currently-visible `required` attrs with
    no value at all — bom_gate.find_missing_required_fields's own
    docstring has the full story (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_
    PLAN.md §2c can deliberately leave a non-decision required attr
    unfilled). Checked FIRST, before the stale-constraint recheck: a
    config that's missing required data outright is a more basic problem
    than one whose filled data has gone stale. No session mutation for
    this case (unlike the stale-value clear-and-reask below) — these
    attrs typically have no menu to re-ask from, so this only reports
    what's missing rather than inventing a question.
    """
    from aryx.api import ask_api as _ask_api_module
    missing_required = find_missing_required_fields(attrs, session)
    if missing_required:
        labels = [
            f"**{a.display_label}**" for a in missing_required
        ]
        return (
            "This configuration is missing required data: " + ", ".join(labels)
            + ". It can't be marked complete until these resolve."
        )
    if not con_rules:
        return _reask_confirmed_data_table_conflict(
            session, attrs, workspace_id, catalog_prefix,
        )
    try:
        stale = recheck_constraints(
            _ask_api_module._cpq_engine, attrs, session, con_rules, bml_eval,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("cpq_proactive_stale_check: constraint recheck failed: %r", exc)
        return None
    if not stale:
        # No stale-but-fixable constraint violation — check for the other
        # class of proven-invalid state _invalidate_inconsistent_paired_
        # values deliberately can't self-correct: a real, Data-Table-proven
        # conflict where BOTH sides are customer-confirmed, so neither can
        # be silently cleared (docs/CPQ_BOTH_CONFIRMED_DATA_TABLE_CONFLICT_
        # REASK_PLAN_2026_08_10.md).
        return _reask_confirmed_data_table_conflict(
            session, attrs, workspace_id, catalog_prefix,
        )
    conflicted = [v for v in stale if not v.allowed]
    if conflicted:
        return handle_conflicted_violations(session, attrs, conflicted)
    stale = silently_reresolve_hard_excluded(session, stale)
    if not stale:
        return _reask_confirmed_data_table_conflict(
            session, attrs, workspace_id, catalog_prefix,
        )
    return build_stale_reask_prompt(session, attrs, stale)
