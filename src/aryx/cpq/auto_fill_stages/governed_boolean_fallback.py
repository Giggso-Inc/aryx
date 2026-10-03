"""Governed boolean with no menu options at all -- defaults to "false".

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.

This was the ``elif`` of ``if not value and attr.options:``, so it
only ever ran when that branch did NOT. As a sequential stage it
carries that mutual exclusion explicitly as ``and not attr.options``
(the branch it followed required ``attr.options`` truthy, and its own
``not value`` clause is unchanged) -- without it, a boolean attr that
DOES have options but resolved nothing in Tier 4 would newly reach
this blind default, which the original ``elif`` prevented.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.auto_fill_stages.state import AttrResolution

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def stage_governed_boolean(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Default a governed, option-less boolean attr to "false"."""
    if state.done:
        return
    if (
        not state.value and state.is_governed and not state.is_decision_attr
        and attr.select_type == "boolean" and scope.display_order is None
        # mutual-exclusion guard for the elif-to-stage conversion --
        # see this module's docstring.
        and not attr.options
    ):
        # Governed boolean with no menu options at all: default to
        # "false" (unchecked) rather than leaving it perpetually
        # pending — a boolean's absent-default state is well-defined.
        # §2f: gated the same way as the sibling branch above — once
        # a layout map is loaded, this blind default is skipped too.
        state.value = "false"
        state.display = "No"
        state.source = state.governed_source
        fill_log.log_decision(state.vn, "stage_governed_boolean", "picked", "GOVERNED_BOOLEAN_DEFAULT_FALSE")
