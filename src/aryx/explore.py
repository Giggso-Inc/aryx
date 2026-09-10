"""Data-explorer aggregation — the transparency surface's read model.

Pure functions over already-fetched entity + provenance lists (the relational
source of truth, via EntityStore). No DB, no graph driver — so the shaping is
unit-testable and the HTTP layer (api/data_api.py) stays a thin wire.

Three reads back the Data tab: a workspace summary (types, counts, sources,
the dedup story) and an entities-by-type view that carries each golden record's
attributes AND the source records it traces back to.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`explore_summary.py` (`summarize`/`entities_view`/`graph_view`) and
`explore_text_match.py` (brief-driven text normalization/matching), both
re-imported here. Zero whitebox test patches exist anywhere against
`aryx.explore.*` (confirmed via grep), so the split was purely mechanical.
`domain_overview_view` — the brief-driven overview orchestrator — stays
here.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from aryx.display_name import display_name  # noqa: F401 — re-exported for callers
from aryx.explore_summary import entities_view, graph_view, summarize
from aryx.explore_text_match import _domain_matches, _matches

__all__ = [
    "_matches",
    "display_name",
    "domain_overview_view",
    "entities_view",
    "graph_view",
    "summarize",
]


def domain_overview_view(
    entities,
    relationships,
    brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a brief-driven overview graph plus highlight metadata.

    The overview is focused by the workspace brief's domain text. If that text
    produces no graph match, the function optionally enriches the query with the
    brief aim/objectives. If the graph still has no match, callers get the
    global type-level overview as a safe fallback.
    """
    entities = list(entities)
    relationships = list(relationships)
    brief = brief or {}
    domain = str(brief.get("domain") or "").strip()
    entity_ids_by_type: dict[str, list[int]] = defaultdict(list)
    for entity_id, entity_type, _attrs in entities:
        entity_ids_by_type[entity_type].append(entity_id)

    def _fallback() -> dict[str, Any]:
        base = graph_view(entities, relationships)
        return {
            "domain": domain,
            "overview_nodes": [
                {
                    "id": f"overview::{node['type']}",
                    "type": node["type"],
                    "count": node["count"],
                    "entity_ids": sorted(entity_ids_by_type[node["type"]]),
                }
                for node in base["type_nodes"]
            ],
            "overview_edges": base["type_edges"],
            "matched_entity_ids": [],
            "matched_edge_pairs": [],
            "matched_types": [],
            "fallback_used": True,
            "entity_count": base["entity_count"],
            "relationship_count": base["relationship_count"],
        }

    if not domain:
        return _fallback()

    matched_ids, matched_types = _domain_matches(entities, domain)
    if not matched_ids:
        aim = str(brief.get("aim") or "").strip()
        objectives = [
            str(item).strip() for item in (brief.get("objectives") or [])
            if str(item).strip()
        ]
        enrichment = " ".join([domain, aim, *objectives]).strip()
        matched_ids, matched_types = _domain_matches(entities, enrichment)

    if not matched_ids:
        return _fallback()

    selected = [(eid, etype, attrs) for eid, etype, attrs in entities if eid in matched_ids]
    type_counts = Counter(etype for _eid, etype, _attrs in selected)
    type_entity_ids: dict[str, list[int]] = defaultdict(list)
    for entity_id, entity_type, _attrs in selected:
        type_entity_ids[entity_type].append(entity_id)

    id_type = {entity_id: entity_type for entity_id, entity_type, _attrs in selected}
    edge_agg: Counter[tuple[str, str, str]] = Counter()
    matched_edge_pair_keys: set[tuple[int, int]] = set()
    matched_edge_pairs: list[dict[str, int]] = []
    for src, tgt, name in relationships:
        stype = id_type.get(src)
        ttype = id_type.get(tgt)
        if not stype or not ttype:
            continue
        edge_agg[(stype, ttype, name)] += 1
        pair = (src, tgt)
        if pair in matched_edge_pair_keys:
            continue
        matched_edge_pair_keys.add(pair)
        matched_edge_pairs.append({"source": src, "target": tgt})

    overview_nodes = [
        {
            "id": f"overview::{entity_type}",
            "type": entity_type,
            "count": count,
            "entity_ids": sorted(type_entity_ids[entity_type]),
        }
        for entity_type, count in type_counts.most_common()
    ]
    overview_edges = [
        {"source": src, "target": tgt, "name": name, "count": count}
        for (src, tgt, name), count in edge_agg.most_common()
    ]
    return {
        "domain": domain,
        "overview_nodes": overview_nodes,
        "overview_edges": overview_edges,
        "matched_entity_ids": sorted(matched_ids),
        "matched_edge_pairs": matched_edge_pairs,
        "matched_types": sorted(matched_types),
        "fallback_used": False,
        "entity_count": len(entities),
        "relationship_count": len(relationships),
    }
