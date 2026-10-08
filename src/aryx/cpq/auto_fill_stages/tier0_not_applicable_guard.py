"""Tier 0 (first) -- skip and clear attrs confirmed not applicable to the
device resolved from the customer's wording (port of dev-rv-msi #364/#365).

Behind ``cpq_not_applicable_guard_enabled``. One-sided and never-guess: only
removes, only when a device is confidently resolved AND Data Table evidence
shows it never governs the attr. Hardware Version uses its own named check;
other structural anchors (required, Product selector) are never checked. A
customer-confirmed ('user' source) value is NEVER cleared.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aryx.config import get_settings
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.raven_log import raven_log, would_log

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr

logger = logging.getLogger(__name__)


def _log_device_once(ctx: "FillContext", scope: "FillScope") -> None:
    """A DEBUG line per cache (a few per turn: the rules loop shares one, the summary and payload paths build their
    own): the models the guard resolves from the customer's wording. Only the LENGTH of the wording is logged, never
    its text (Raven decision records hold no customer text); the models are catalog data.

    The guard does nothing when the wording does not resolve to a confident set of models, and it said nothing about
    that (ws 1267, 2026-10-07: APX 4500 dropped its irrelevant attributes, APX N30 dropped none, and the logs could not
    say why). Diagnostic only: any failure is swallowed.
    """
    try:
        if not would_log("DEBUG"):
            return
        cache = ctx.dt_cache
        key = ("_not_applicable_guard_device_logged", scope.workspace_id, scope.catalog_prefix)
        if cache is not None:
            if key in cache:
                return
            cache[key] = True
        from aryx.cpq.data_table.data_table_resolver import resolve_product_cpq_models_from_hint  # noqa: PLC0415

        hint = scope.product_anchor_hint
        models = (resolve_product_cpq_models_from_hint(hint, scope.workspace_id, scope.catalog_prefix, cache)
                  if hint and scope.workspace_id is not None else ())
        raven_log("DEBUG", "P4", "ask.guard.device_resolved not-applicable guard device from the customer wording", context={
            "selected_option": "device_resolved" if models else "device_unresolved",
            "available_options": ["device_resolved", "device_unresolved"],
            "reason_code": "GUARD_DEVICE_RESOLVED" if models else "GUARD_DEVICE_UNRESOLVED_NO_OP",
            "hint_len": len(hint or ""), "models": list(models)[:12], "model_count": len(models)})
    except Exception:  # noqa: BLE001 -- a diagnostic must never change the fill
        return


def _is_resolved_anchor(vn: str) -> bool:
    """With `cpq_model_scoped_questions_enabled`: the decision anchors the engine resolves itself (country, product, base
    model, region) are never cleared as 'not applicable'. A model's sequence rows often do not list the base model
    attribute, so the guard cleared it (ws 1267, APX N30: `TIER0_NOT_APPLICABLE_GUARD` on `modelSelectionbaseModel_astro`
    in every pass), the derivation that follows never ran, and with no base model nothing else could be scoped. Off:
    the guard behaves as before."""
    if not getattr(get_settings(), "cpq_model_scoped_questions_enabled", False):
        return False
    from aryx.cpq.data_table_bridge.attr_governance import _scoped_anchor_vns  # noqa: PLC0415 -- the one anchor list

    return vn in _scoped_anchor_vns()


def stage_not_applicable_guard(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Skip (and clear any earlier blind fill of) a not-applicable attr."""
    if state.done or not get_settings().cpq_not_applicable_guard_enabled:
        return
    _log_device_once(ctx, scope)
    vn = state.vn
    if ctx.sources.get(vn) == "user":
        return  # customer-confirmed value is never cleared
    if engine._is_hardware_version_attr(attr):
        not_applicable = engine._hardware_version_confirmed_not_applicable(
            scope.product_anchor_hint, scope.workspace_id, scope.catalog_prefix,
            ctx.dt_cache,
        )
    elif attr.required or engine._is_product_line_selector(attr):
        return
    elif _is_resolved_anchor(vn):
        return
    else:
        not_applicable = engine._named_attr_confirmed_not_applicable(
            vn, scope.product_anchor_hint, scope.workspace_id,
            scope.catalog_prefix, ctx.dt_cache,
        )
    if not not_applicable:
        return
    if vn in ctx.filled:
        logger.info(
            "cpq: clearing previously blind-filled %r=%r -- confirmed no "
            "concept for this resolved device (hint_len=%d)",
            vn, ctx.filled[vn], len(scope.product_anchor_hint or ""),
        )
    ctx.filled.pop(vn, None)
    ctx.display_filled.pop(vn, None)
    ctx.sources.pop(vn, None)
    ctx.filled_multi.pop(vn, None)
    state.done = True
