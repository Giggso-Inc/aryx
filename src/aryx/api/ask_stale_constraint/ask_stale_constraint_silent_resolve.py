"""Silent re-resolution of hard-excluded attrs whose staleness narrowed
to exactly one legal value, split out of `ask_stale_constraint_reask.py`
(Phase 4/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). Logic unchanged from the original inline block.
"""

from __future__ import annotations

import logging
from typing import Any

from aryx.api.ask_pending_exclusion import _NEVER_ASK_RECOMMENDED_ONLY_VNS

logger = logging.getLogger(__name__)


def silently_reresolve_hard_excluded(session: Any, stale: list) -> list:
    """2026-08-19 fix (live-confirmed via a real APX NEXT transcript:
    "Constraint Package Type Based on Bundle Type" narrows Package Type
    to exactly ONE legal value here, yet it was still being cleared and
    re-asked as "choose one: 1. Single Pack Clamshell" -- a technically
    correct but pointless single-option menu). `_hard_exclude_from_
    pending`'s own attribute allowlist (native UI never asks this
    conversationally) applies here just as much as it does at the 6
    cascade/change call sites -- this function is simply an 8th write
    path those never covered. When a hard-excluded attribute's staleness
    narrows to exactly one legal value (the same `len(allowed) == 1`
    trust bar `_hard_exclude_from_pending` itself uses -- 2+ remaining
    values is still a real, unresolved choice, not a computed answer),
    silently re-fill it with that value instead of re-asking. Every
    other stale attribute in `stale` is unaffected -- only ever applies
    to this individually-vetted allowlist.

    Returns the remaining still-stale violations (those not silently
    resolved this way).
    """
    still_stale: list = []
    for v in stale:
        vn = v.attr.variable_name
        if (
            vn in _NEVER_ASK_RECOMMENDED_ONLY_VNS
            and v.attr.select_type != "multi"
            and v.allowed
            and len(v.allowed) == 1
        ):
            chosen_value = v.allowed[0]
            chosen_opt = next(
                (o for o in v.attr.options if o.item_value == chosen_value), None,
            )
            if chosen_opt is not None:
                session.filled[vn] = chosen_opt.item_value
                session.display_filled[vn] = chosen_opt.display_name
                session.filled_source[vn] = "rule"
                logger.info(
                    "cpq: %r silently re-resolved instead of stale-reasked "
                    "(native UI never asks this conversationally) -- "
                    "resolved to %r", vn, chosen_value,
                )
                continue
        still_stale.append(v)
    return still_stale
