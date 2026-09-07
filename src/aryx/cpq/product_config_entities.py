"""`load_product_config`'s Step 1+2 (Phase 4, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md): discover the config-attr entity type(s), scope to the
requested product's catalog, paginate-fetch every entity, then batch-fetch
their PostgreSQL rows. Logic unchanged from the original inline block.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.engine import logger


def _norm(t: str) -> str:
    return (t or "").lower().replace("_", "")


def load_attr_entities(
    engine: Any, reader: Any, workspace_id: int, product_hint: str,
) -> tuple[list[dict], dict[int, dict], str, list[str]]:
    """Returns (attr_ents, attr_pg, resolved_catalog_prefix, all_type_names)."""
    # Step 1 — find config attr entities. XML ingestion prefixes type names
    # per source (e.g. ApxNextConfigBmConfigAttr, Sl3500EDummyConfigBmConfigAttr),
    # so discover the actual type name(s) first via DISTINCT types, then fetch
    # by exact type. Sampling find_entities(limit=1000) instead is unreliable:
    # on a 46k-entity graph the arbitrary first page can contain zero
    # ConfigAttr rows even though hundreds exist.
    try:
        all_type_names = reader.distinct_types()
    except AttributeError:  # reader without distinct_types — legacy fallback
        all_type_names = sorted({
            e.get("type") or "" for e in reader.find_entities(limit=1000)
        })
    attr_types = [t for t in all_type_names if _norm(t).endswith("configattr")]
    if not attr_types:
        attr_types = [
            t for t in all_type_names
            if "configattr" in _norm(t) and not engine._is_layout_noise(t)
        ]

    # Scope to the single catalog the requested product belongs to —
    # a workspace may hold more than one ingested product catalog at
    # once (see _scope_to_catalog docstring). resolved_catalog_prefix
    # is stamped onto every ConfigAttr below so rule loaders can apply
    # the same scoping without needing a second graph round-trip.
    attr_types, resolved_catalog_prefix = engine._scope_to_catalog(
        reader, workspace_id, attr_types, product_hint,
    )

    attr_ents: list[dict] = []
    for attr_type in attr_types:
        # Paginate past find_entities' capped limit — confirmed live
        # (2026-07-27, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md
        # Amendment 13): a single limit=500 call silently truncated
        # CommandCentral Aware's 906 real BmConfigAttr rows down to
        # 324 loaded, dropping hundreds of attrs including
        # hiddenHidingRuleMasterStringForCommandCentral_swSoln — the
        # exact gotcha find_entities' own docstring already documents
        # for BmMenuItem (SL3500e's >2000 rows), just never applied
        # here. Loop until a short page confirms there's nothing left.
        offset = 0
        while True:
            page = reader.find_entities(ontology_type=attr_type, limit=500, offset=offset)
            attr_ents.extend(page)
            if len(page) < 500:
                break
            offset += 500

    if not attr_ents:
        logger.info("cpq: no bm_config_attr entities found in graph "
                    "(workspace_id=%s, types_seen=%d)",
                    workspace_id, len(all_type_names))
        return [], {}, resolved_catalog_prefix, all_type_names

    # Step 2 — batch fetch PostgreSQL attributes
    attr_ids = [e["id"] for e in attr_ents]
    attr_pg = engine._batch_fetch(attr_ids, workspace_id)
    return attr_ents, attr_pg, resolved_catalog_prefix, all_type_names
