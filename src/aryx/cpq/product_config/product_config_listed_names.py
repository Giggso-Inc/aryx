"""Attribute names the catalog itself lists (flag ``cpq_keep_listed_noise_named_attrs_enabled``).

The loader drops an attribute whose name CONTAINS a noise fragment ("test", "pager", "error", "dummy"). A real attribute
can contain one inside an ordinary word: ws 281, APX N50, ``documentationTest...`` ("Test Results/Rated Audio Printout
Label", required for the model, default NO) was thrown away as if it were a ``TestPager``, so it was never asked,
defaulted or listed. A true noise attribute is listed in no model's sequence; this one is. So an attribute the
AttrSequence lists is kept. No attribute name is involved: the answer comes from the table.

ws 1267 (APX 3000 / 900 / N30) has no AttrSequence row for it, but every stored layout of the catalog places it in the
Documentation section, so the names any stored layout places count as listed too.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.config import get_settings
from aryx.cpq.data_table.data_table_loader import _load_all_tables

logger = logging.getLogger(__name__)


def _sequence_names(workspace_id: int, catalog_prefix: str) -> set[str]:
    try:
        _constraint, sequence_rows, *_rest = _load_all_tables(workspace_id, catalog_prefix, None)
        return {name for name in (str(row.get("AttrName") or "").strip() for row in sequence_rows) if name}
    except Exception:  # noqa: BLE001 -- keeping more attributes is a nicety, never a reason to break the load
        logger.debug("cpq: attrSequence names for the noise filter failed", exc_info=True)
        return set()


def _layout_names(engine: Any, workspace_id: int, catalog_prefix: str) -> set[str]:
    """Variable names placed by any stored layout of the catalog (the default one and every variant). A layout that
    fails to load is skipped; the others still count."""
    from aryx.cpq.layout_source import DEFAULT_LAYOUT_VARIANT  # noqa: PLC0415

    try:
        from aryx.cpq.layout_and_join_data.layout_variant import stored_variant_keys  # noqa: PLC0415

        variants = [DEFAULT_LAYOUT_VARIANT, *stored_variant_keys(workspace_id, catalog_prefix)]
    except Exception:  # noqa: BLE001 -- same: a nicety, never a reason to break the load
        logger.debug("cpq: layout variants for the noise filter failed", exc_info=True)
        variants = [DEFAULT_LAYOUT_VARIANT]
    names: set[str] = set()
    for variant in variants:
        try:
            components = (engine._load_layout_components(workspace_id, catalog_prefix, None)
                          if variant == DEFAULT_LAYOUT_VARIANT
                          else engine._load_layout_components(workspace_id, catalog_prefix, None, variant))
        except Exception:  # noqa: BLE001
            logger.debug("cpq: layout %r for the noise filter failed", variant, exc_info=True)
            continue
        names.update(str(c.get("resourceAttributeVarName") or "") for c in components or [])
    names.discard("")
    return names


def listed_attr_names(workspace_id: int | None, catalog_prefix: str, engine: Any = None) -> frozenset[str]:
    """The AttrNames of the workspace's AttrSequence rows, plus (with `engine`) the names its stored layouts place, or
    empty (flag off / no table / any failure)."""
    if workspace_id is None or getattr(get_settings(), "cpq_keep_listed_noise_named_attrs_enabled", False) is not True:
        return frozenset()
    names = _sequence_names(workspace_id, catalog_prefix)
    if engine is not None:
        names |= _layout_names(engine, workspace_id, catalog_prefix)
    return frozenset(names)
