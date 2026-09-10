"""`auto_fill`'s same-slot optional-attribute conflict detection (Phase 4,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md), split out of the P0
setup block. Logic unchanged from the original inline block.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.engine import _valid


def compute_conflicted_optional_ids(
    engine: Any, attrs: list[Any], governed: set[int], rule_governed: set[int],
) -> set[int]:
    """Two "optional"-tier attrs (no rule, no default — eligible only via
    the widened Phase N fallback) that share a real option value are
    very likely the same underlying hardware/accessory concept exported
    as separate BM attributes (confirmed live: spSurveillancePackagesType_
    astro and spSurveillancePackagesTypes_astro both offer "Impress 3-Wire
    Surveillance Kit - Black" — picking first-by-order for each
    independently produced Beige AND Black in the same quote). Rule-
    governed attrs (a real rule already backs the value) are excluded —
    this is purely a same-slot-detector for otherwise-independent fields.
    """
    option_value_owners: dict[str, set[int]] = {}
    for a in attrs:
        if (a.hidden or a.entity_id not in governed or a.entity_id in rule_governed
                or a.select_type == "multi"):
            continue
        for opt in a.options:
            iv_norm = opt.item_value.strip().upper()
            # Generic yes/no-shaped values are shared by dozens of
            # unrelated boolean-ish attrs (quickStartGuide, dualBand,
            # etc.) — real signal only comes from specific values a
            # coincidence wouldn't produce (e.g. a shared SKU/kit name).
            if _valid(opt.item_value) and iv_norm.lower() not in engine._BOOLEAN_DISPLAY_VALUES:
                option_value_owners.setdefault(iv_norm, set()).add(a.entity_id)
    conflicted_optional_ids: set[int] = set()
    for owners in option_value_owners.values():
        if len(owners) > 1:
            conflicted_optional_ids.update(owners)
    return conflicted_optional_ids
