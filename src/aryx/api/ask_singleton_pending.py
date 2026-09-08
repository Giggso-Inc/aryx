"""Late re-check of `pending[0]`'s live constraints right before it would
be asked, split out of `api/ask_api.py` (Phase 4/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic
unchanged from the original inline definition. `_cpq_engine` is read
through the ask_api MODULE object (not imported by name) since at least
one test replaces the whole singleton via
`patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

import logging
from typing import Any

from aryx.api import ask_api as _ask_api_module
from aryx.cpq.engine import _valid

logger = logging.getLogger(__name__)


def _auto_resolve_singleton_pending(
    pending: list, filled: dict, display_filled: dict, filled_source: dict,
    con_rules: list, bml_eval: Any,
    workspace_id: int | None = None, catalog_prefix: str = "",
) -> list:
    """Live bug: `auto_fill`'s own "constraint narrows to exactly one legal
    value -> auto-fill, never ask" mechanism only ever sees the constraint
    evaluation available AT THE MOMENT auto_fill() ran. A script-backed
    constraint rule (e.g. Package Type's real ICE-KIT-gated rule,
    18131370895) can depend on BmlEvaluator's Tier-2 (LLM) path when Tier
    1's deterministic parser doesn't support its idiom (confirmed live:
    no findinArray/findInArray handling in bml.evaluate_tier1) -- if that
    evaluation hasn't resolved yet when auto_fill() runs, the attribute
    lands in `pending` even though, by the time its question is actually
    about to be presented, the SAME constraint has since narrowed to a
    single legal value. Every one of ask_api's 6 independent auto_fill()
    call sites did `next_attr = pending[0]` and asked immediately after,
    with no re-check in between -- this closes that gap in one shared
    place instead of duplicating the fix 6 times.

    Re-evaluates `pending[0]`'s live constraints one more time right
    before it would be asked; if exactly one legal value remains, fills
    it silently and moves on to the new pending[0] (looping, since
    resolving one attribute can itself let the next one narrow too, the
    same cascade auto_fill's own fixed-point loop already relies on).
    Never touches multi-select attrs (auto_fill's own "exactly one
    value" shortcut is single-select-only by design -- a multi-select
    genuinely narrowed to one legal box is a different, already-handled
    "select all constrained candidates" case, not a forced single value).
    Any evaluation failure degrades to leaving `pending` untouched -- this
    is a best-effort late narrowing, never a hard requirement for the
    turn to proceed.
    """
    if not pending or not con_rules or bml_eval is None:
        return pending
    pending = list(pending)
    while pending:
        attr = pending[0]
        if attr.select_type == "multi" or not attr.options:
            break
        try:
            allowed = _ask_api_module._cpq_engine.apply_constraint_rules(
                [attr], con_rules, filled, bml_eval,
                workspace_id=workspace_id, catalog_prefix=catalog_prefix,
            ).get(attr.entity_id)
        except Exception:  # noqa: BLE001 — best-effort, never blocks the turn
            logger.debug(
                "cpq: singleton-pending re-check failed for %r",
                attr.variable_name, exc_info=True,
            )
            break
        if not allowed:
            break
        valid_opts = [
            o for o in attr.options
            if _valid(o.item_value) and o.item_value in allowed
        ]
        if len(valid_opts) != 1:
            break
        opt = valid_opts[0]
        filled[attr.variable_name] = opt.item_value
        display_filled[attr.variable_name] = opt.display_name
        filled_source.setdefault(attr.variable_name, "rule")
        logger.info(
            "cpq: singleton-pending %r auto-resolved to %r right before "
            "asking -- its constraint narrowed to one legal value after "
            "auto_fill() ran but before this question was presented",
            attr.variable_name, opt.item_value,
        )
        pending = pending[1:]
    return pending
