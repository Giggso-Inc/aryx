"""Proactive re-ask for a confirmed Data-Table-proven attribute conflict,
split out of `api/ask_api.py` (Phase 4/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from
the original inline definition. `_cpq_engine` is read through the
ask_api MODULE object (not imported by name) since at least one test
replaces the whole singleton via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

import logging
from typing import Any

from aryx.api import ask_api as _ask_api_module
from aryx.cpq.pending_scope import set_pending_scope
from aryx.cpq.session_guard import push_snapshot

logger = logging.getLogger(__name__)


def _reask_confirmed_data_table_conflict(
    session: Any, attrs: list, workspace_id: int | None, catalog_prefix: str,
) -> str | None:
    """The specific edge case `CpqEngine._invalidate_inconsistent_paired_
    values` deliberately can't self-correct: a real, Data-Table-proven
    conflict where BOTH sides of a linked pair are customer-confirmed
    (`CpqEngine._CONFIRMED_SOURCES`), so neither can be silently cleared.
    Surfaces an explicit re-ask instead of letting the invalid combination
    reach the final BOM (docs/CPQ_BOTH_CONFIRMED_DATA_TABLE_CONFLICT_
    REASK_PLAN_2026_08_10.md). Best-effort — a lookup failure never blocks
    "Configuration complete" on this proactive check; returns None.
    """
    try:
        confirmed_conflicts = _ask_api_module._cpq_engine.find_confirmed_data_table_conflicts(
            session.filled, session.filled_source, workspace_id, catalog_prefix,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "cpq_proactive_stale_check: data-table conflict check failed: %r", exc,
        )
        return None
    if not confirmed_conflicts:
        return None
    attr_a_vn, attr_b_vn = next(iter(confirmed_conflicts))
    by_vn = {a.variable_name: a for a in attrs}
    attr_a, attr_b = by_vn.get(attr_a_vn), by_vn.get(attr_b_vn)
    if attr_a is None or attr_b is None:
        return None
    push_snapshot(session, reason="confirmed_data_table_conflict_reask")
    for vn in (attr_a_vn, attr_b_vn):
        session.filled.pop(vn, None)
        session.display_filled.pop(vn, None)
        session.filled_source.pop(vn, None)
    session.pending_variables = [attr_a_vn, attr_b_vn] + [
        v for v in session.pending_variables if v not in (attr_a_vn, attr_b_vn)
    ]
    session.status = "configuring"
    session.complete = False
    label_a = _ask_api_module._cpq_engine.disambiguated_label(attr_a, attrs)
    label_b = _ask_api_module._cpq_engine.disambiguated_label(attr_b, attrs)
    prompt = _ask_api_module._cpq_engine.next_question_prompt(attr_a, attrs=attrs)
    # 2026-08-18 fix: sync pending_scope to the list just shown above, or
    # the next reply gets validated against whatever candidates were left
    # over from BEFORE this re-ask (stale, narrower list) — confirmed live:
    # a customer's exact, verbatim answer from THIS prompt ("Single XE")
    # was rejected as "no match" because pending_scope_candidates still
    # held the prior turn's 1-item list. `attr_a.options` here is the same
    # source `next_question_prompt` renders its numbered list from.
    set_pending_scope(
        session,
        kind="attr_options",
        candidates=[o.display_name for o in attr_a.options],
        origin_question=prompt,
        attr_vn=attr_a_vn,
        asked_turn=session.turn,
    )
    return (
        f"⚠️ **Rule conflict detected.** Your selections for **{label_a}** "
        f"and **{label_b}** are incompatible — the catalog's own data "
        f"proves these two values can't be combined. Please change one "
        f"of them.\n\n{prompt}\n\n"
        f"*(I'll also ask about **{label_b}** next.)*"
    )
