"""Pending-list prune for attrs confirmed not applicable to the resolved
device (port of dev-rv-msi #362).

A shared multi-model layout marks components visible for the whole file, so
attrs belonging to another product line leak into ``pending``. Real Data
Table evidence (``attr_ever_governed_for_cpq_model``) tells the safe
direction: an attr never governed for any resolved CPQModel candidate is
irrelevant. One-sided: only removes, never adds; no-op when the hint is
unresolved. The ``dt_*`` resolvers are looked up through ``aryx.cpq.engine``
at call time so tests patching ``aryx.cpq.engine.<name>`` take effect.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aryx.cpq.state import ConfigAttr

logger = logging.getLogger(__name__)


def is_structural_anchor(attr: "ConfigAttr") -> bool:
    """Anchors are exempt: catalog `required`, Hardware Version, Product."""
    from aryx.cpq.engine import CpqEngine

    return (
        bool(attr.required)
        or CpqEngine._is_hardware_version_attr(attr)
        or CpqEngine._is_product_line_selector(attr)
    )


def attrs_confirmed_not_applicable_for_hint(
    pending: list["ConfigAttr"], hint_text: str | None,
    workspace_id: int | None, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> list["ConfigAttr"]:
    """Return `pending` minus attrs never governed for the resolved device."""
    if not hint_text or workspace_id is None or not pending:
        return pending
    from aryx.cpq import engine as _engine

    candidates = _engine.dt_resolve_product_cpq_models_from_hint(
        hint_text, workspace_id, catalog_prefix, cache,
    )
    if not candidates:
        return pending
    kept: list["ConfigAttr"] = []
    for attr in pending:
        vn = attr.variable_name or ""
        if not vn or is_structural_anchor(attr):
            kept.append(attr)
            continue
        if any(
            _engine.dt_attr_ever_governed_for_cpq_model(
                cm, vn, workspace_id, catalog_prefix, cache,
            )
            for cm in candidates
        ):
            kept.append(attr)
            continue
        logger.info(
            "cpq: dropping pending attr %r -- never governed for any "
            "resolved CPQModel candidate %r (hint=%r)",
            vn, candidates, hint_text,
        )
    return kept
