"""Search the catalog's attribute menu options, per ingested product family.

On real data most attribute values (e.g. carrier "ATT/FIRSTNET") live as
menu options on the catalog's configuration attributes -- not in
attrToVarMapping or the constraint rows (checked on workspace 704,
2026-10-02). For each family, load its config (CpqEngine.load_product_config),
ground the phrase against the attributes' display labels, and keep the
options matching the value. A hit's `model` is the family name, which is
what a quote is later started from.

Yes/no attributes and which attributes are searchable at all are defined
in searchable.py.

The phrase is grounded once against every family's labels, so a loose
match in one family never beats an exact match in another.

load_product_config costs ~10-17s per family on workspace 704, so each
family's (label, variable, options) snapshot is cached per workspace and
cleared when the catalog is re-ingested (same re-ingest marker as
data_table_product's attrToVarMapping cache). The marker guarantees
freshness, so the TTL is long (6 h) -- a 5-minute TTL made an idle chat's
next search cold (PR #423 review). Families load in parallel, at most 2 at
a time, and a family that fails to load isn't retried for 60 s.
"""
from __future__ import annotations

import concurrent.futures
import logging
import time
from typing import Any

from aryx.cpq.attribute_search.ground import ground_attribute_label, value_variants
from aryx.cpq.attribute_search.searchable import (
    Entry,
    boolean_code,
    option_matches,
    searchable_entry,
    yes_no,
)
from aryx.cpq.data_table import data_table_cache
from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)

_TTL_SECONDS = 6 * 3600.0
_FAILED_TTL_SECONDS = 60.0
# At most 2 family loads at once across all requests (DB pool headroom).
_FAMILY_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="attr-search-family",
)
# (workspace_id, family) -> when its load last failed
_FAILED: dict[tuple[int, str], float] = {}
# (workspace_id, family) -> (cached_at, [entry, ...])
_MENU_CACHE: dict[tuple[int, str], tuple[float, list[Entry]]] = {}
_MENU_CACHE_LAST_SEEN_MARKER: list[float | None] = [None]


def clear_menu_cache() -> None:
    """Drop every cached family snapshot (tests, or after a known re-ingest)."""
    _MENU_CACHE.clear()
    _FAILED.clear()
    _MENU_CACHE_LAST_SEEN_MARKER[0] = None


def _family_snapshot(
    engine: Any, reader: Any, workspace_id: int, family: str,
) -> list[Entry] | None:
    """Searchable attributes (with options, or real yes/no); None if the family fails to load."""
    marker = data_table_cache._invalidate_on_marker_change(
        _MENU_CACHE, _MENU_CACHE_LAST_SEEN_MARKER,
    )
    key = (workspace_id, family)
    hit = _MENU_CACHE.get(key)
    now = time.monotonic()
    if hit is not None and now - hit[0] < _TTL_SECONDS:
        return hit[1]
    if now - _FAILED.get(key, -_FAILED_TTL_SECONDS) < _FAILED_TTL_SECONDS:
        return None
    try:
        attrs, _resolved = engine.load_product_config(reader, workspace_id, family)
    except Exception as exc:  # noqa: BLE001 -- one bad family must not end the search
        logger.warning("attribute_search: load_product_config(%r) failed: %s", family, exc)
        raven_log("WARN", "P3", "ask.attr_search.family_skipped one family's menus could not load",
                  error_code="ARYX_ASK_ATTR_SEARCH_FAMILY_SKIPPED",
                  context={"triggering_error": type(exc).__name__, "attempt": 1, "max_attempts": 1,
                           "backoff_ms": 0, "recovery_selected": "skip_family", "fallback_target": None,
                           "exit_condition": "skipped", "result": "skipped", "family": family,
                           "workspace_id": workspace_id})
        _FAILED[key] = now
        return None
    _FAILED.pop(key, None)
    snapshot = [e for e in (searchable_entry(a) for a in attrs) if e is not None]
    data_table_cache._cache_write_if_marker_unchanged(
        _MENU_CACHE, key, (time.monotonic(), snapshot), marker,
    )
    return snapshot


def search_menu_options(
    phrase: str, value: str | None, *, reader: Any, engine: Any, workspace_id: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Menu options matching `value` under attributes matching `phrase`.

    Args:
        phrase: Attribute as the user typed it, e.g. "carrier".
        value: Value as typed, e.g. "ATT"; None returns every option.
        reader: Graph reader for the workspace.
        engine: CpqEngine (list_ingested_families / load_product_config).
        workspace_id: Workspace to search.

    Returns:
        (hits, grounded_labels). Each hit: model (family), base_model,
        attribute (variable name), value (option display name, or "Yes"/
        "No" for a yes/no attribute), label, kind ("option" | "boolean"),
        item_value (the code to store), select_type.
    """
    if reader is None or engine is None:
        return [], []
    spellings = value_variants(value or "")
    answer = yes_no(value)
    hits: list[dict[str, Any]] = []
    families = list(engine.list_ingested_families(reader, workspace_id))
    loaded = _FAMILY_POOL.map(
        lambda family: _family_snapshot(engine, reader, workspace_id, family) or [], families,
    )
    snapshots = dict(zip(families, loaded))
    all_labels = list(dict.fromkeys(e[0] for snap in snapshots.values() for e in snap))
    labels = ground_attribute_label(phrase, all_labels)
    for family, snapshot in snapshots.items():
        for label, variable, options, is_boolean, select_type in snapshot:
            if label not in labels:
                continue
            hit = {"model": family, "base_model": None, "attribute": variable, "label": label,
                   "select_type": select_type}
            if is_boolean:
                code = boolean_code(options, answer) if answer is not None else None
                if code is not None:
                    hits.append({**hit, "value": answer, "kind": "boolean", "item_value": code})
                continue
            for option in options:
                if spellings and not option_matches(option, spellings):
                    continue
                hits.append({**hit, "value": option.display_name, "kind": "option",
                             "item_value": option.item_value})
    return hits, sorted(labels)
