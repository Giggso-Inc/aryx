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
import threading
import time
from typing import Any

from aryx.config import get_settings
from aryx.cpq.data_table.data_table_loader import _load_all_tables
from aryx.raven_log import raven_log

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


_LAYOUT_NAMES_MEMO: dict[tuple[int, str], frozenset[str]] = {}
_LAYOUT_NAMES_LOCK = threading.Lock()


def _memo_layout_names(engine: Any, workspace_id: int, catalog_prefix: str, sequence: set[str]) -> frozenset[str]:
    """`_layout_names`, computed once per (workspace, catalog prefix) for the process (the layout components behind it
    are cached for the process too). The first computation logs its cost and the noise-named attributes the layouts
    keep beyond the AttrSequence, so the widening is visible per catalog."""
    key = (workspace_id, catalog_prefix)
    with _LAYOUT_NAMES_LOCK:
        if key in _LAYOUT_NAMES_MEMO:
            return _LAYOUT_NAMES_MEMO[key]
    started = time.monotonic()
    names = frozenset(_layout_names(engine, workspace_id, catalog_prefix))
    if not names:
        return names                             # nothing loaded (no layout yet, or a failure): try again next load
    with _LAYOUT_NAMES_LOCK:
        _LAYOUT_NAMES_MEMO[key] = names
    from aryx.cpq.region_and_noise_constants import _NOISE_VAR_FRAGMENTS  # noqa: PLC0415

    layout_only_noise = sorted(n for n in names - sequence if any(f in n.lower() for f in _NOISE_VAR_FRAGMENTS))
    raven_log("INFO", "P4", "ask.load.noise_listed_layout_names layout names for the noise filter computed", context={
        "selected_option": "computed", "available_options": ["computed", "memoized"],
        "reason_code": "LAYOUT_LISTED_NAMES", "workspace_id": workspace_id, "catalog_prefix": catalog_prefix,
        "duration_ms": int((time.monotonic() - started) * 1000), "layout_name_count": len(names),
        "noise_named_kept_by_layout_only": layout_only_noise[:50],
        "noise_named_kept_by_layout_only_count": len(layout_only_noise)})
    return names


def _clear_memo() -> None:
    """Tests only."""
    with _LAYOUT_NAMES_LOCK:
        _LAYOUT_NAMES_MEMO.clear()


def listed_attr_names(workspace_id: int | None, catalog_prefix: str, engine: Any = None) -> frozenset[str]:
    """The AttrNames of the workspace's AttrSequence rows, plus (with `engine`) the names its stored layouts place, or
    empty (flag off / no table / any failure)."""
    if workspace_id is None or getattr(get_settings(), "cpq_keep_listed_noise_named_attrs_enabled", False) is not True:
        return frozenset()
    names = _sequence_names(workspace_id, catalog_prefix)
    if engine is not None:
        names |= _memo_layout_names(engine, workspace_id, catalog_prefix, names)
    return frozenset(names)
