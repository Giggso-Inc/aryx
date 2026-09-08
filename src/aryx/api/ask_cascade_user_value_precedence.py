"""Reverting a rule-pass override of the customer's just-chosen cascade
value, split out of `_handle_cascade`'s post-rule-loop reconciliation
(Phase 4/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md) purely to keep the sibling `ask_cascade_recompute.py`
under the line cap. Logic unchanged from the original inline block.
"""

from __future__ import annotations

from typing import Any


def _revert_overridden_user_value(
    session: Any, changed_attr: Any, result: tuple, pending: list,
) -> tuple:
    """D1, docs/CPQ_USER_VALUE_PRECEDENCE_PLAN.md: the value the customer
    just explicitly chose is authoritative input for the REST of this
    turn's evaluation — if the rule pass above silently reassigned it
    (e.g. a stably-true recommendation rule targeting the same attr,
    live-verified: Billing Option -> "Annual" silently became
    "Immediate"), revert rather than reporting the substituted value as
    if it were accepted. Scoped to single-select only (a multi-select's
    own union semantics are a different question, not this bug's
    shape). Checking the OUTCOME here catches the bug regardless of
    which internal mechanism causes it — no changes to auto_fill/
    apply_recommendation_rules/evaluate_rules_loop needed, and every
    OTHER attribute's cascade above is completely unaffected.

    Returns (user_value_overridden, requested_display, pending) — the
    caller must re-derive `session.pending_variables` from the returned
    `pending` list, matching the original inline mutation exactly.
    """
    user_value_overridden = (
        changed_attr.select_type != "multi" and result
        and session.filled.get(changed_attr.variable_name) != result[0]
    )
    requested_display = None
    if user_value_overridden:
        requested_display = result[1]
        session.filled.pop(changed_attr.variable_name, None)
        session.display_filled.pop(changed_attr.variable_name, None)
        session.filled_source.pop(changed_attr.variable_name, None)
        pending = [changed_attr] + [
            a for a in pending if a.variable_name != changed_attr.variable_name
        ]
        session.pending_variables = [a.variable_name for a in pending]
    return user_value_overridden, requested_display, pending
