"""Tier 1 -- match the user's NL hints against this attr's options.

Lifted verbatim from the pre-split ``auto_fill_resolve.py``
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md,
the resolve_one_attr stage split) -- logic unchanged; the function's
shared locals now live on ``AttrResolution``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import re

from aryx.cpq.auto_fill_stages.state import AttrResolution
from aryx.cpq.engine import (
    _country_alias_group,
    _valid,
)

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def stage_hint_match(
    engine: "CpqEngine",
    attr: "ConfigAttr",
    ctx: "FillContext",
    scope: "FillScope",
    state: AttrResolution,
) -> None:
    """Resolve a value from `scope.hints` (4 descending priorities)."""
    if state.done:
        return
    # 1. User hint matching — strip underscores/case, check fragment containment
    for hint_key, hint_val in scope.hints.items():
        hk_flat = hint_key.lower().replace("_", "")
        if hk_flat in state.vn_flat or state.vn_flat in hk_flat:
            hv_lower = hint_val.lower()
            # Priority 1: exact item_value match (e.g. hint="US" → item_value="US")
            for opt in attr.options:
                if opt.item_value.lower() == hv_lower:
                    state.value = opt.item_value
                    state.display = opt.display_name
                    break
            # Priority 2: exact display_name match (prevents "United States"
            # matching "United States Minor Outlying Islands" via word-boundary)
            if not state.value:
                for opt in attr.options:
                    if opt.display_name.lower() == hv_lower:
                        state.value = opt.item_value
                        state.display = opt.display_name
                        break
            # Priority 3: word-boundary display match (catches partial names,
            # prevents "us" matching "Austria")
            if not state.value:
                for opt in attr.options:
                    if re.search(r"\b" + re.escape(hv_lower) + r"\b",
                                 opt.display_name.lower()):
                        state.value = opt.item_value
                        state.display = opt.display_name
                        break
            # Priority 4: country alias group (bidirectional) —
            # a hint value that's ANY known alias for a country
            # (full name, official name, alpha-2, alpha-3, or
            # common colloquial name) matches an option whose own
            # item_value/display_name is any OTHER alias in the
            # same group. Fixed 2026-08-14: the old lookup was
            # keyed one-directionally (full name -> abbreviation
            # only), so a hint value that was ITSELF an
            # abbreviation (e.g. "usa") could never look anything
            # up — `_COUNTRY_HINT_SHORTHAND.get("usa", ())` always
            # returned empty since "usa" was never a dict key.
            # _country_alias_group is symmetric, closing that gap
            # for real, for all 249 real ISO countries, not just
            # the 2 the old dict hand-covered.
            if not state.value and hint_key == "country":
                alias_group = _country_alias_group(hv_lower)
                if alias_group:
                    for opt in attr.options:
                        if (opt.item_value.lower() in alias_group
                                or opt.display_name.lower() in alias_group):
                            state.value = opt.item_value
                            state.display = opt.display_name
                            break
            # Never assign an arbitrary hint string to a boolean-typed
            # attr just because its name fragment-matched a hint key
            # (e.g. "country" is a substring of
            # "isUltimateDestinationCountryCA_astro") — confirmed
            # live against the real CPQ API: this attr is a genuine
            # boolean (data_type=4, real default "false"), and the
            # fragment match wrongly assigned the literal country
            # name "United States" to it, which the API rejected
            # ("has to be either true or false"). A boolean attr's
            # only valid values are true/false, never a hint's
            # free-text content.
            if (not state.value and not attr.options and _valid(hint_val)
                    and attr.select_type != "boolean"):
                state.value = hint_val
                state.display = hint_val
            if state.value:
                state.source = "hint"
            break
