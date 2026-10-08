"""Once the base model is known, an attribute the customer did not answer takes the base model's default.

Behind ``cpq_base_model_defaults_enabled``. The first pass fills attributes before the base model exists (the first
or only option of a rule-governed attribute, tagged "rule"), and later passes keep a value with that tag, so the
base model's own Defaultinattr row was never reached (ws 281, APX N30: antenna STANDARD instead of WHIP, keypad
NO KEYPAD instead of LIMITED KEYPAD, data cable YES instead of NO).

Two stages, so the default has the right place in the order of precedence (the customer's words, then a
recommendation rule that applies now, then the base model's default, then the generic default):

* ``stage_base_model_default_clear`` (right after the not-applicable guard, before ``tier0_already_filled``):
  only removes an earlier pick that may be replaced and differs from the default, so the attribute is empty again.
* ``stage_base_model_default_fill`` (after ``tier2_satisfied_rec``, before ``tier3_default_value``): writes the
  default only when the hint stage and the recommendation stage left the attribute empty.

A value from the customer, their wording or the session is never replaced. The default must be an option the
active constraints still allow. Hidden attributes, multi-selects (their own flag), the decision anchors and the
attributes the governance stage always asks (country / region / hardware version / select-model / base model) are
not touched. A value this stage wrote has its own source (``defaultinattr``); it is replaced when the base model
changes and its default differs.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.base_model_defaults import base_model_defaults
from aryx.cpq.base_model_narrowing import value_matches
from aryx.cpq.catalog_profile import resolve_base_model_vn
from aryx.cpq.derive_base_model_pick import blind_attrs
from aryx.cpq.fill_signature import _DECISION_REQUIRED_KEYS
from aryx.cpq.model_scoping_flags import base_model_defaults_enabled, scoped_anchor_vns

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr, MenuOption

DEFAULTINATTR_SOURCE = "defaultinattr"
# A pick made before the base model existed (the engine's tag for a governed pick), or an earlier default of
# another base model. A guess is replaceable too (`blind_attrs`).
_REPLACEABLE_PREFIXES = ("rule", DEFAULTINATTR_SOURCE)
# The attributes the governance stage always asks (kept in step with `governance_flags.stage_governance_flags`).
_ALWAYS_ASKED_FRAGMENTS = (*_DECISION_REQUIRED_KEYS, "basemodel", "selectmodel")


def _replaceable(vn: str, source: str | None) -> bool:
    return source is None or str(source).startswith(_REPLACEABLE_PREFIXES) or vn in blind_attrs({vn: source})


def _always_asked(engine: "CpqEngine", attr: "ConfigAttr", vn_flat: str) -> bool:
    return any(key in vn_flat for key in _ALWAYS_ASKED_FRAGMENTS) or engine._is_hardware_version_attr(attr)


def _option_for(attr: "ConfigAttr", scope: "FillScope", default: str) -> "MenuOption | None":
    """The attribute's option the default names (by item value or display name) that the constraints allow."""
    wanted = {default.strip().upper()}
    allowed = scope.constrained_opts.get(attr.entity_id) if scope.constrained_opts else None
    for option in attr.options:
        if not value_matches(wanted, option.item_value, option.display_name):
            continue
        return None if allowed is not None and option.item_value not in allowed else option
    return None


def _default_option(
    engine: "CpqEngine", attr: "ConfigAttr", ctx: "FillContext", scope: "FillScope", state: AttrResolution,
) -> "MenuOption | None":
    """The option that is this attribute's base model default, or None when the stages do not apply to it."""
    if not base_model_defaults_enabled() or scope.workspace_id is None:
        return None
    vn = state.vn
    if attr.hidden or attr.select_type == "multi" or not attr.options or vn in scoped_anchor_vns():
        return None
    if _always_asked(engine, attr, state.vn_flat):
        return None
    base_vn = resolve_base_model_vn(ctx.filled, scope.workspace_id, scope.catalog_prefix, ctx.dt_cache)
    base_model = ctx.filled.get(base_vn, "")
    if not base_model or base_vn in blind_attrs(ctx.sources):
        return None                               # no (real) base model yet: nothing to take defaults from
    defaults = base_model_defaults(base_model, scope.workspace_id, scope.catalog_prefix, ctx.dt_cache)
    default = defaults.get(vn)
    return None if default is None else _option_for(attr, scope, default)


def stage_base_model_default_clear(
    engine: "CpqEngine", attr: "ConfigAttr", ctx: "FillContext", scope: "FillScope", state: AttrResolution,
) -> None:
    """Empty the attribute again when it holds an earlier pick that may be replaced and is not the default."""
    vn = state.vn
    if state.done or vn not in ctx.filled:
        return
    option = _default_option(engine, attr, ctx, scope, state)
    if option is None or str(ctx.filled[vn]).strip().upper() == option.item_value.strip().upper():
        return
    if not _replaceable(vn, ctx.sources.get(vn)):
        return                                    # the customer's, their wording's or another source's value stays
    fill_log.log_pruned(vn, "BASE_MODEL_DEFAULT_REPLACES_EARLIER_PICK", "stage_base_model_default_clear",
                        state="replaced")
    ctx.filled.pop(vn, None)
    ctx.display_filled.pop(vn, None)
    ctx.sources.pop(vn, None)


def stage_base_model_default_fill(
    engine: "CpqEngine", attr: "ConfigAttr", ctx: "FillContext", scope: "FillScope", state: AttrResolution,
) -> None:
    """Write the default when the hint and recommendation stages left the attribute empty."""
    if state.done or state.value or state.vn in ctx.filled:
        return
    option = _default_option(engine, attr, ctx, scope, state)
    if option is None:
        return
    state.value, state.display, state.source = option.item_value, option.display_name, DEFAULTINATTR_SOURCE
    fill_log.log_decision(state.vn, "stage_base_model_default_fill", "filled", "DEFAULTINATTR_FOR_BASE_MODEL")
