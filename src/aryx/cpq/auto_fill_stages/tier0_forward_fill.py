"""Tier 0d -- fill an attribute that separates the model's base models from a base model the customer already has.

Base model narrowing (flag `cpq_base_model_narrowing_enabled`). The mapping between a base model and the attributes
that identify it runs both ways: with the base model known (typed, or chosen from the list) its frequency band and
keypad type follow, so they are not asked again. Only an UNANSWERED, visible attribute is filled, never one the
customer answered, and the value must be one of the attribute's own options.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.auto_fill_stages.state import AttrResolution

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def stage_forward_fill(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Set `state.value` from the known base model's own row value; later stages and the commit do the rest."""
    narrowing = scope.base_model_narrowing
    if state.done or state.value or narrowing is None or state.vn not in narrowing.forward:
        return
    target = narrowing.forward[state.vn]
    for option in attr.options:
        if option.item_value.strip().upper() == target or option.display_name.strip().upper() == target:
            state.value = option.item_value
            state.display = option.display_name
            state.source = "derived_from_base_model"
            fill_log.log_decision(state.vn, "base_model_narrowing", "filled", "FORWARD_FROM_BASE_MODEL")
            return
