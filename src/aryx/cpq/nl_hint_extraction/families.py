"""``list_ingested_families`` (Phase 4 step 11 extraction from
``cpq/engine.py`` -- see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`_catalog_prefix` is read off the engine MODULE object; `_batch_fetch`
goes back through the passed-in `engine` instance.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq import engine as _engine_module


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
