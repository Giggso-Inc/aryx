"""Optional attributes with nothing to justify a value are left unanswered (flag `cpq_no_blind_fill_optional_enabled`).

ws 1267, APX 3000: Mission Critical Wireless Accessory Bundle is optional, has no Defaultinattr default and the Whitelist
leaves 3 values, yet it was filled "Accessory Bundle Pack 1" (`default_first_available`, then `blind_pick_*`) and went
into the BOM. The real screen offers "None". A blind first-option pick is a guess, never evidence, and for an optional
attribute the safe answer is no answer."""
from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.config import get_settings

if TYPE_CHECKING:
    from aryx.cpq.auto_fill_stages.state import AttrResolution
    from aryx.cpq.state import ConfigAttr


def optional_without_basis(attr: "ConfigAttr", state: "AttrResolution") -> bool:
    """True when the blind first-option stages must skip this attribute: flag on, single-select (or multi-select too with
    `cpq_no_blind_fill_optional_multi_enabled`), not catalog-required, not a decision/forced-ask/derived-required
    attribute. Everything with a real basis (hint, recommendation, data
    table, default) was resolved by an earlier stage and never reaches the blind stages."""
    settings = get_settings()
    if getattr(settings, "cpq_no_blind_fill_optional_enabled", False) is not True:
        return False
    # ws 1267, APX N30: the multi-select Feature Type (additionalSystemEnhancementFeatureType_astro) reached the
    # attrSequence-governed blind pick and got "Disable Cloud Services", a value the real screen does not show
    # (flag `cpq_no_blind_fill_optional_multi_enabled` covers multi-selects too).
    multi_ok = getattr(settings, "cpq_no_blind_fill_optional_multi_enabled", False) is True
    return (attr.select_type != "multi" or multi_ok) and not attr.required and not state.is_decision_attr
