"""Identifies FK joins across entity type schemas via batched LLM calls —
type-level FK discovery, applied by the caller via link_by_attribute to ALL
matching entities, not just the handful sampled here.

Split out of `pipeline/enrich.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.relationships import infer_fk_links
from aryx.store.entity_store import EntityStore

logger = logging.getLogger(__name__)


def _infer_one_batch(
    batch_types: list[str], type_schemas: dict[str, dict], anchor_type: str,
    broker: Broker,
) -> list[dict[str, Any]]:
    """Run one batch's LLM inference call. Every batch is independent (its
    own non-overlapping type subset plus the shared anchor), so this is safe
    to call concurrently — errors are caught per-batch (best-effort) rather
    than failing the whole inference pass."""
    batch_keys = [anchor_type] + batch_types
    batch_schemas = {t: type_schemas[t] for t in batch_keys if t in type_schemas}
    try:
        return infer_fk_links(batch_schemas, broker)
    except Exception:  # noqa: BLE001 — schema inference is best-effort
        logger.exception("schema FK inference failed for batch %s — skipping", batch_keys)
        return []


def _infer_schema_fk_links(store: EntityStore, broker: Broker) -> list[dict[str, Any]]:
    """Identify FK joins across entity type schemas via batched LLM calls.

    Samples one entity per type to get actual column names, then asks the LLM
    which attributes form FK relationships between types.  The caller applies
    the result via link_by_attribute which creates edges for ALL matching
    entities — not just the handful sampled for _relate.

    When there are more than _BATCH_SIZE types, the schemas are split into
    overlapping batches so each LLM call stays within the token budget.
    Each batch always contains the "anchor" type (the one with the most FK-like
    attributes) so cross-batch FK links involving the anchor are discovered.
    """
    try:
        sample = store.list_entities_typed_sample(1)
    except Exception:  # noqa: BLE001 — schema FK inference is best-effort
        logger.exception("_infer_schema_fk_links: typed sample query failed — skipping")
        return []
    if len(sample) < 2:
        return []

    _MAX_SCHEMA_ATTRS = 8   # reduced per-type to fit more types per call
    _BATCH_SIZE = 8          # max types per LLM call — keeps output under 768 tok
    _SNAKE_FK = ("_id", "_code", "_key", "_ref", "_type", "_no", "_num")
    _CAMEL_FK = ("Id", "Code", "Key", "Ref", "Type", "No", "Num")

    type_schemas: dict[str, dict] = {}
    for _eid, etype, attrs in sample:
        public_attrs = [k for k in attrs if not k.startswith("_")]
        fk_first = [
            k for k in public_attrs
            if k.lower().endswith(_SNAKE_FK) or k.endswith(_CAMEL_FK)
        ]
        other_attrs = [k for k in public_attrs if k not in set(fk_first)]
        schema_attrs = (fk_first + other_attrs)[:_MAX_SCHEMA_ATTRS]
        type_schemas[etype] = {
            "attrs": schema_attrs,
            "match_keys": [],
            "_fk_count": len(fk_first),
        }

    # Anchor = type with most FK-like columns; always included in each batch
    # so that cross-batch FK links involving the anchor are detected.
    anchor_type = max(type_schemas, key=lambda t: type_schemas[t]["_fk_count"])
    non_anchor = [t for t in type_schemas if t != anchor_type]

    # Clean up internal key before sending to LLM.
    for t in type_schemas:
        type_schemas[t].pop("_fk_count", None)

    all_links: list[dict[str, Any]] = []
    seen: set[tuple] = set()

    # Build batches: anchor + up to (_BATCH_SIZE - 1) other types.
    batch_size = _BATCH_SIZE - 1
    batches = [
        non_anchor[i: i + batch_size]
        for i in range(0, max(1, len(non_anchor)), batch_size)
    ] or [[]]

    # Batches are independent (own non-overlapping type subset, shared
    # anchor, deduplicated into `seen` regardless of completion order) — see
    # P17 in docs/raven/SCALABILITY_BOTTLENECKS.md. Run them concurrently
    # instead of one LLM call after another; dedup still happens on the main
    # thread as each future resolves, so it's identical to the old
    # sequential result, just not sequential wall-clock time.
    workers = max(1, get_settings().fk_schema_batch_workers)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_infer_one_batch, batch_types, type_schemas, anchor_type, broker)
            for batch_types in batches
        ]
        for future in as_completed(futures):
            for lnk in future.result():
                key = (lnk.get("source_type"), lnk.get("source_attr"),
                       lnk.get("target_type"), lnk.get("target_attr"))
                if key not in seen:
                    seen.add(key)
                    all_links.append(lnk)

    if all_links:
        logger.info(
            "schema FK inference found %d link(s) across %d batch(es): %s",
            len(all_links), len(batches), all_links,
        )
    return all_links
