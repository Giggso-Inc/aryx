"""Catalog facts the per-turn model resolver reads (``model_resolution``).

Loads, once per (workspace, catalog prefix) and cached for ten minutes, the
real ingested rows the resolver needs: ``Basemodeltoconfig`` (display name ->
cpqModel -> base models), the ``<prefix>BmCatalog`` tree, ``Flagsforflashport``
(upgrade radios) and ``<prefix>BmConfigRule`` (rule name -> owning node ids).
Reads go through ``CpqRdb.fetch_entities_by_exact_type``, which both the
Postgres and Oracle accessors implement, so nothing here is dialect specific.
No product-specific code. Split out of ``model_resolution`` to keep each
module small.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from aryx.cpq.logging_context import install_run_id_logging

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)

_CACHE_TTL_S = 600.0


@dataclass
class CatalogData:
    """Aggregated, read-only catalog facts for one workspace + prefix."""

    loaded_at: float
    models: dict[str, dict[str, Any]]  # cpqModel -> aggregated Basemodeltoconfig facts
    nodes_by_id: dict[str, tuple[str, str]]  # native id -> (name, parent_id)
    node_id_by_name: dict[str, str]  # lower(name) -> native id
    upgrade_models: frozenset[str]
    upgrade_node_ids: frozenset[str]
    rule_nodes_by_name: dict[str, frozenset[str]]  # lower(rule name) -> owning ref_ids


_cache: dict[tuple[int, str], CatalogData] = {}
# Empty results (DB error OR a catalog that is genuinely not ingested) are
# remembered only briefly: long enough not to re-scan on every call, short
# enough that a transient error recovers quickly.
_EMPTY_TTL_S = 30.0
_empty: dict[tuple[int, str], CatalogData] = {}
_cache_lock = threading.Lock()


def cached(workspace_id: int, catalog_prefix: str) -> CatalogData | None:
    """The already-loaded data for this key, or None (never loads)."""
    return _cache.get((int(workspace_id), catalog_prefix or ""))


def _fetch(rdb: Any, workspace_id: int, ontology_type: str) -> list[dict[str, Any]]:
    return [attrs for _eid, attrs in rdb.fetch_entities_by_exact_type(workspace_id, ontology_type)]


def _load_models(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    models: dict[str, dict[str, Any]] = {}
    for row in rows:
        cpq = str(row.get("cpqModel") or "").strip()
        if not cpq:
            continue
        m = models.setdefault(cpq, {"display": set(), "varnames": set(), "base_models": set()})
        if row.get("displayModel"):
            m["display"].add(str(row["displayModel"]).strip())
        if row.get("CPQModelVariableName"):
            m["varnames"].add(str(row["CPQModelVariableName"]).strip())
        if row.get("baseModel"):
            m["base_models"].add(str(row["baseModel"]).strip())
    return models


def _node_for(cpq: str, varnames: set[str], node_id_by_name: dict[str, str]) -> str | None:
    for name in [*sorted(varnames), cpq]:
        for variant in (name, re.sub(r"_bom$", "", name, flags=re.I)):
            nid = node_id_by_name.get(variant.lower())
            if nid:
                return nid
    return None


def load_catalog(workspace_id: int, catalog_prefix: str, rdb: Any | None = None) -> CatalogData:
    """Return (building on a cache miss) the catalog facts for the key."""
    key = (int(workspace_id), catalog_prefix or "")
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and now - hit.loaded_at < _CACHE_TTL_S:
            return hit
        miss = _empty.get(key)
        if miss is not None and now - miss.loaded_at < _EMPTY_TTL_S:
            return miss
    if rdb is None:
        from aryx.cpq.rdb import get_cpq_rdb
        rdb = get_cpq_rdb()

    nodes_by_id: dict[str, tuple[str, str]] = {}
    for row in _fetch(rdb, workspace_id, f"{catalog_prefix}BmCatalog"):
        nid = str(row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        if nid and name:
            nodes_by_id[nid] = (name, str(row.get("parent_id") or "").strip())
    node_id_by_name = {name.lower(): nid for nid, (name, _p) in nodes_by_id.items()}

    models = _load_models(_fetch(rdb, workspace_id, "Basemodeltoconfig"))
    for cpq, m in models.items():
        m["node_id"] = _node_for(cpq, m["varnames"], node_id_by_name)

    upgrade_models = frozenset(
        str(r.get("cpqModel") or "").strip()
        for r in _fetch(rdb, workspace_id, "Flagsforflashport")
        if r.get("cpqModel")
    )
    upgrade_node_ids = frozenset(
        models[c]["node_id"] for c in upgrade_models if c in models and models[c]["node_id"]
    )

    rule_nodes: dict[str, set[str]] = {}
    for row in _fetch(rdb, workspace_id, f"{catalog_prefix}BmConfigRule"):
        name = str(row.get("name") or "").strip().lower()
        if name:
            rule_nodes.setdefault(name, set()).add(str(row.get("ref_id") or "").strip())

    data = CatalogData(
        loaded_at=time.monotonic(), models=models, nodes_by_id=nodes_by_id,
        node_id_by_name=node_id_by_name, upgrade_models=upgrade_models,
        upgrade_node_ids=upgrade_node_ids,
        rule_nodes_by_name={k: frozenset(v) for k, v in rule_nodes.items()},
    )
    if not nodes_by_id or not models:
        # fetch_entities_by_exact_type swallows DB errors and returns [], so an
        # empty result is indistinguishable from a transient failure, so
        # keep it only briefly (_EMPTY_TTL_S): a long-lived empty entry would
        # leave the workspace unresolved for the full catalog TTL.
        logger.warning(
            "cpq: model_resolution catalog empty ws=%s prefix=%r nodes=%d models=%d "
            "-- short-lived empty cache (%.0fs; possible DB error or catalog not ingested)",
            workspace_id, catalog_prefix, len(nodes_by_id), len(models), _EMPTY_TTL_S,
        )
        with _cache_lock:
            _empty[key] = data
        return data
    with _cache_lock:
        _cache[key] = data
    return data


def invalidate(workspace_id: int | None = None) -> None:
    """Drop cached catalogs (one workspace, or all). Call after a re-ingest."""
    with _cache_lock:
        for store in (_cache, _empty):
            for k in [k for k in store if workspace_id is None or k[0] == int(workspace_id)]:
                del store[k]


def catalog_node_count(workspace_id: int, catalog_prefix: str) -> int:
    """``BmCatalog`` node count as the relational store holds it."""
    return len(load_catalog(workspace_id, catalog_prefix).nodes_by_id)


def ancestors(node_id: str | None, nodes_by_id: dict[str, tuple[str, str]]) -> list[str]:
    """``node_id`` and every ancestor up to the root (cycle-safe)."""
    out: list[str] = []
    seen: set[str] = set()
    cur = node_id
    while cur and cur not in seen and cur in nodes_by_id:
        seen.add(cur)
        out.append(cur)
        parent = nodes_by_id[cur][1]
        cur = parent if parent and parent != "-1" else None
    return out
