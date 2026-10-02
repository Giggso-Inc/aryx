"""Per-turn model-resolution binding and the flag-gated consumers that sit in
the model-leaf step (aryxent PR 1/2 and the pick-top rule), split out of
`ask_model_leaf_resolve.py` to keep each file small.

``bind_turn_model_context`` resolves which catalog model the customer's
wording (this turn plus the product anchor question) refers to and binds it
via ``aryx.cpq.model_resolution`` so later stages can read it. It runs only
when ``cpq_model_resolution_enabled`` is on; otherwise it just clears any
stale binding. It never raises and never changes the turn on its own.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from aryx.api.ask_model_leaf.ask_model_leaf_norm import _norm_leaf
from aryx.config import get_settings
from aryx.cpq import model_resolution as _model_resolution
from aryx.cpq.logging_context import install_run_id_logging

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)


def bind_turn_model_context(
    req: Any, session: Any, catalog_prefix: str, switch_trigger_question: str | None,
) -> None:
    """Resolve and bind this turn's model context (flag-gated, never raises)."""
    _model_resolution.bind_turn(None)
    if not get_settings().cpq_model_resolution_enabled:
        return
    try:
        hint = " ".join(
            p for p in (
                getattr(session, "product_anchor_question", "") or "",
                switch_trigger_question or "",
                getattr(req, "question", "") or "",
            ) if p
        )
        t0 = time.monotonic()
        turn_text = " ".join(
            p for p in (switch_trigger_question or "", getattr(req, "question", "") or "") if p
        )
        res = _model_resolution.resolve_model_turn_first(
            turn_text, getattr(session, "product_anchor_question", "") or "",
            req.workspace_id, catalog_prefix,
        )
        _model_resolution.bind_turn(
            _model_resolution.TurnModelContext(res, req.workspace_id, catalog_prefix),
        )
        logger.info(
            "cpq: model_resolution %s hint=%r elapsed_s=%.3f",
            _model_resolution.describe(res), hint[:200], time.monotonic() - t0,
        )
    except Exception:  # noqa: BLE001 -- resolution must never affect the turn
        logger.exception("cpq: model_resolution failed (turn unaffected)")


def resolved_node_name() -> str | None:
    """Node name of the bound turn's resolved model, or None."""
    ctx = _model_resolution.get_turn()
    if ctx is None or not ctx.resolution.resolved or ctx.resolution.chosen is None:
        return None
    return ctx.resolution.chosen.node_name or None


def seed_model_vn_from_resolution() -> str:
    """PR 2: the resolved model's node name when `cpq_model_context_seed_enabled`
    is on, else ''. Callers use it only when the single-leaf mechanism found
    nothing."""
    if not get_settings().cpq_model_context_seed_enabled:
        return ""
    return resolved_node_name() or ""


def pick_top_text_match(text_matches: list[str]) -> str | None:
    """When 2+ leaves match the wording and `cpq_model_leaf_pick_top_enabled`
    is on (and ``cpq_model_resolution_enabled`` too), the leaf to take instead of asking: the resolver's chosen node if
    it is one of the matches, else the longest-named match (alphabetical
    tie-break). None when the flag is off or there is nothing to pick."""
    settings = get_settings()
    if (
        len(text_matches) < 2 or not settings.cpq_model_leaf_pick_top_enabled
        or not settings.cpq_model_resolution_enabled
    ):
        return None
    node = resolved_node_name()
    pick = next((m for m in text_matches if node and _norm_leaf(m) == _norm_leaf(node)), None)
    if pick is None:
        pick = sorted(text_matches, key=lambda m: (-len(_norm_leaf(m)), m))[0]
    logger.info(
        "cpq: model_leaf picked top match %r among %r (not asking; resolver node=%r)",
        pick, text_matches, node,
    )
    return pick
