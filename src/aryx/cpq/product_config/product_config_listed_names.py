"""Attribute names the catalog's own AttrSequence table lists (flag ``cpq_keep_listed_noise_named_attrs_enabled``).

The loader drops an attribute whose name CONTAINS a noise fragment ("test", "pager", "error", "dummy"). A real attribute
can contain one inside an ordinary word: ws 281, APX N50, ``documentationTest...`` ("Test Results/Rated Audio Printout
Label", required for the model, default NO) was thrown away as if it were a ``TestPager``, so it was never asked,
defaulted or listed. A true noise attribute is listed in no model's sequence; this one is. So an attribute the
AttrSequence lists is kept. No attribute name is involved: the answer comes from the table.
"""
from __future__ import annotations

import logging

from aryx.config import get_settings
from aryx.cpq.data_table.data_table_loader import _load_all_tables

logger = logging.getLogger(__name__)


def listed_attr_names(workspace_id: int | None, catalog_prefix: str) -> frozenset[str]:
    """The AttrNames of the workspace's AttrSequence rows, or empty (flag off / no table / any failure)."""
    if workspace_id is None or getattr(get_settings(), "cpq_keep_listed_noise_named_attrs_enabled", False) is not True:
        return frozenset()
    try:
        _constraint, sequence_rows, *_rest = _load_all_tables(workspace_id, catalog_prefix, None)
        return frozenset(name for name in (str(row.get("AttrName") or "").strip() for row in sequence_rows) if name)
    except Exception:  # noqa: BLE001 -- keeping more attributes is a nicety, never a reason to break the load
        logger.debug("cpq: attrSequence names for the noise filter failed", exc_info=True)
        return frozenset()
