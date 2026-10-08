"""Tier 0 -- once the base model is known, an attribute the customer did not answer takes the base model's default.

Behind ``cpq_base_model_defaults_enabled``. The first pass fills attributes before the base model exists (the first or only
option of a rule-governed attribute, tagged "rule"), and later passes keep a value with that tag, so the base model's own
Defaultinattr row was never reached (ws 281, APX N30: antenna STANDARD instead of WHIP, keypad NO KEYPAD instead of LIMITED
KEYPAD, data cable YES instead of NO). This stage replaces such a pick by the default.

One-sided: a value from the customer or their wording, or from a recommendation rule that is satisfied now, is kept. The
default must be a real option the active constraints still allow. Hidden attributes, multi-selects (their own flag) and the
decision anchors are not touched. Placed before the already-filled stage so it can replace a value; a value it sets has its
own source (``defaultinattr``), which no later pass replaces.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.base_model_defaults import base_model_defaults
from aryx.cpq.catalog_profile import resolve_base_model_vn
from aryx.cpq.model_scoping_flags import base_model_defaults_enabled, scoped_anchor_vns

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr

DEFAULTINATTR_SOURCE = "defaultinattr"
_GUESS_PREFIXES = ("blind_pick", "default_first_available")
# A value that may be replaced: a pick made before the base model existed (the engine's tag for a governed pick), or a guess.
_REPLACEABLE_PREFIXES = ("rule", *_GUESS_PREFIXES)


def _replaceable(source: str | None) -> bool:
    return source is None or str(source).startswith(_REPLACEABLE_PREFIXES)


def _option_for(attr: "ConfigAttr", scope: "FillScope", default: str):
    """The attribute's option equal to `default` (case-insensitive) that the active constraints still allow, or None."""
    wanted = default.strip().upper()
    allowed = scope.constrained_opts.get(attr.entity_id) if scope.constrained_opts else None
    for option in attr.options:
        if option.item_value.strip().upper() != wanted:
            continue
        if allowed is not None and option.item_value not in allowed:
            return None
        return option
    return None


def stage_base_model_default(
    engine: "CpqEngine", attr: "ConfigAttr", ctx: "FillContext", scope: "FillScope", state: AttrResolution,
) -> None:
    """Set `state.value` to the base model's default, replacing an earlier pick; later stages commit it."""
    if state.done or state.value or not base_model_defaults_enabled() or scope.workspace_id is None:
        return
    vn = state.vn
    if attr.hidden or attr.select_type == "multi" or not attr.options or vn in scoped_anchor_vns():
        return
    base_vn = resolve_base_model_vn(ctx.filled, scope.workspace_id, scope.catalog_prefix, ctx.dt_cache)
    base_model = ctx.filled.get(base_vn, "")
    if not base_model or str(ctx.sources.get(base_vn, "")).startswith(_GUESS_PREFIXES):
        return                                    # no (real) base model yet: nothing to take defaults from
    default = base_model_defaults(base_model, scope.workspace_id, scope.catalog_prefix, ctx.dt_cache).get(vn)
    if default is None:
        return
    option = _option_for(attr, scope, default)
    if option is None:
        return                                    # not a real option, or a constraint excludes it: the other stages decide
    if vn in ctx.filled:
        if str(ctx.filled[vn]).strip().upper() == default.strip().upper():
            return                                # already the default
        if not _replaceable(ctx.sources.get(vn)):
            return                                # the customer's, their wording's, or another source's value stays
        if scope.rec_by_target and scope.satisfied_recommendation(attr, list(attr.options)):
            return                                # a recommendation rule that applies now decides, not the table
        fill_log.log_pruned(vn, "BASE_MODEL_DEFAULT_REPLACES_EARLIER_PICK", "stage_base_model_default", state="replaced")
        ctx.filled.pop(vn, None)
        ctx.display_filled.pop(vn, None)
        ctx.sources.pop(vn, None)
    state.value, state.display, state.source = option.item_value, option.display_name, DEFAULTINATTR_SOURCE
    fill_log.log_decision(vn, "stage_base_model_default", "filled", "DEFAULTINATTR_FOR_BASE_MODEL")
