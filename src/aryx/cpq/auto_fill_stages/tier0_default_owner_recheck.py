"""Re-check a base model that was derived as the model's default owner (flag
``cpq_derive_base_model_default_owner_enabled``).

The default owner's pick (`derive_base_model_default_owner`) is a default, not a Whitelist fact: no constraint ever
drops it, so ``tier0_already_filled`` would keep it for good. This stage runs before that one on the base model
attribute and removes the value when the derivation, run again with what is known now, no longer gives the same base
model through the same path (the customer named another band, an attribute now separates the base models, ...). The
base model is then derived again later in the same pass or asked. Values from other sources are never touched.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.catalog_profile import resolve_base_model_vn
from aryx.cpq.derive_base_model_default_owner import DEFAULT_OWNER_SOURCE, default_owner_enabled
from aryx.cpq.derive_base_model_pick import derived_base_model_choice

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def stage_default_owner_recheck(
    engine: "CpqEngine", attr: "ConfigAttr", ctx: "FillContext", scope: "FillScope", state: AttrResolution,
) -> None:
    """Empty the base model attribute again when its default-owner value no longer holds."""
    vn = state.vn
    if state.done or vn not in ctx.filled or ctx.sources.get(vn) != DEFAULT_OWNER_SOURCE:
        return
    if not default_owner_enabled() or scope.workspace_id is None or not attr.options:
        return
    if vn != resolve_base_model_vn(ctx.filled, scope.workspace_id, scope.catalog_prefix, ctx.dt_cache):
        return
    others = {k: v for k, v in ctx.filled.items() if k != vn}
    choice = derived_base_model_choice(attr.options, others, scope.workspace_id, scope.catalog_prefix, ctx.dt_cache,
                                       sources={k: s for k, s in ctx.sources.items() if k != vn})
    current = str(ctx.filled[vn]).strip().upper()
    if choice is not None and choice[1] == "DERIVED_FROM_DEFAULT_OWNER":
        if choice[0].item_value.strip().upper() == current:
            return
    fill_log.log_pruned(vn, "DEFAULT_OWNER_NO_LONGER_HOLDS", "stage_default_owner_recheck", state="reopened")
    ctx.filled.pop(vn, None)
    ctx.display_filled.pop(vn, None)
    ctx.sources.pop(vn, None)
