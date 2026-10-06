"""``list_ingested_families`` (Phase 4 step 11 extraction from
``cpq/engine.py`` -- see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`_catalog_prefix` is read off the engine MODULE object; `_batch_fetch`
goes back through the passed-in `engine` instance.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from aryx.cpq import engine as _engine_module
from aryx.raven_log import raven_log, would_log


def list_ingested_families(engine: Any, reader: Any, workspace_id: int) -> list[str]:
    """Real family/catalog display names, one per ingested catalog
    prefix — for building a dynamic "what product family?" prompt
    instead of a hardcoded example string that goes stale the moment a
    new catalog is ingested."""
    try:
        all_type_names = reader.distinct_types()
    except AttributeError:
        all_type_names = sorted({
            e.get("type") or "" for e in reader.find_entities(limit=1000)
        })
    prefixes = sorted({
        _engine_module._catalog_prefix(t) for t in all_type_names
        if _engine_module._catalog_prefix(t)
    })
    names: list[str] = []
    for prefix in prefixes:
        family_ents = reader.find_entities(
            ontology_type=f"{prefix}BmPrdFamily", limit=5)
        if not family_ents:
            continue
        family_pg = engine._batch_fetch([e["id"] for e in family_ents], workspace_id)
        fname = str(
            family_pg.get(family_ents[0]["id"], {}).get("name")
            or family_ents[0].get("name") or ""
        ).strip()
        if fname:
            names.append(fname)
    return names


def ingested_family_labels(engine: Any, reader: Any, workspace_id: int) -> dict[str, str]:
    """{family name -> human display label} for every ingested catalog.

    Keys are exactly ``list_ingested_families``'s names (the identity Ask
    resolves/matches on, e.g. ``aSTRO25_bom``); values are the entity's
    ``display_label`` (e.g. ``ASTRO®25_BOM``, written by the raw-graph
    locale-wrapper fold -- docs/ingestion/CPQ_XML_DISPLAY_NAMES_PLAN_2026-10-05.md),
    falling back to the name itself. Display only -- never use a value as
    a lookup key.
    """
    t0 = time.monotonic()
    try:
        all_type_names = reader.distinct_types()
    except AttributeError:
        all_type_names = sorted({
            e.get("type") or "" for e in reader.find_entities(limit=1000)
        })
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ask.family_labels.reader_fallback distinct_types unsupported, scanned entities instead",
                      context={"dependency_name": "reader.distinct_types", "operation": "distinct_types",
                               "duration_ms": int((time.monotonic() - t0) * 1000), "result": "fallback",
                               "error_class": "AttributeError", "attempt": 1, "trace_id": str(uuid.uuid4()),
                               "triggering_error": "AttributeError", "max_attempts": 1, "backoff_ms": 0,
                               "recovery_selected": "scan_entities", "fallback_target": "find_entities",
                               "exit_condition": "reader_lacks_distinct_types"})
    prefixes = sorted({
        _engine_module._catalog_prefix(t) for t in all_type_names
        if _engine_module._catalog_prefix(t)
    })
    labels: dict[str, str] = {}
    for prefix in prefixes:
        family_ents = reader.find_entities(
            ontology_type=f"{prefix}BmPrdFamily", limit=5)
        if not family_ents:
            continue
        attrs = engine._batch_fetch([e["id"] for e in family_ents], workspace_id).get(
            family_ents[0]["id"], {})
        fname = str(attrs.get("name") or family_ents[0].get("name") or "").strip()
        if fname:
            labels[fname] = str(attrs.get("display_label") or "").strip() or fname
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ask.family_labels.computed display labels built for ingested families",
                  context={"task_id": f"family-labels-{workspace_id}", "final_status": "done",
                           "duration_ms": int((time.monotonic() - t0) * 1000), "stage": "ingested_family_labels",
                           "result": "ok", "reason_code": "LABELS_BUILT", "impact_scope": f"workspace:{workspace_id}",
                           "dependency_name": "engine._batch_fetch", "operation": "batch_fetch", "error_class": "none",
                           "attempt": 1, "trace_id": str(uuid.uuid4()), "label_count": len(labels)})
    return labels
