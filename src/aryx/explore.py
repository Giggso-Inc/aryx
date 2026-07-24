"""Data-explorer aggregation — the transparency surface's read model.

Pure functions over already-fetched entity + provenance lists (the relational
source of truth, via EntityStore). No DB, no graph driver — so the shaping is
unit-testable and the HTTP layer (api/data_api.py) stays a thin wire.

Three reads back the Data tab: a workspace summary (types, counts, sources,
the dedup story) and an entities-by-type view that carries each golden record's
attributes AND the source records it traces back to.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from aryx.display_name import display_name  # noqa: F401 — re-exported for callers

_STOPWORDS = {
    "a", "an", "and", "by", "for", "from", "in", "of", "on", "or",
    "the", "to", "with",
}
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _prov_by_entity(provenance: list[tuple[int, str, str, str]]) -> dict[int, list[dict]]:
    """Group (entity_id, system, dataset, record_id) rows by entity."""
    out: dict[int, list[dict]] = defaultdict(list)
    for entity_id, system, dataset, record_id in provenance:
        out[int(entity_id)].append(
            {"system": system, "dataset": dataset, "record_id": str(record_id)})
    return out


def summarize(entities, provenance) -> dict[str, Any]:
    """Workspace-level counts: per-type, per-source, and the dedup story."""
    entities = list(entities)
    provenance = list(provenance)
    type_counts = Counter(t for _, t, _ in entities)
    src_counts: Counter = Counter(
        f"{system}.{dataset}" for _, system, dataset, _ in provenance)
    total = len(entities)
    source_records = len(provenance)
    return {
        "total_entities": total,
        "type_count": len(type_counts),
        "types": [{"name": name, "count": count}
                  for name, count in type_counts.most_common()],
        "sources": [{"source": src, "count": count}
                    for src, count in src_counts.most_common()],
        "source_records": source_records,
        "duplicates_merged": max(0, source_records - total),
    }


def entities_view(entities: list[tuple[int, str, dict]],
                  provenance: list[tuple[int, str, str, str]],
                  ontology_type: str | None = None,
                  limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Entities (optionally filtered by type) with attributes + provenance.

    Returns the page plus the unfiltered count for that type so the UI can
    paginate without a second call.
    """
    by_entity = _prov_by_entity(provenance)
    rows = [e for e in entities
            if not ontology_type or e[1] == ontology_type]
    total = len(rows)
    capped = max(1, min(int(limit), 200))
    start = max(0, int(offset))
    page = rows[start:start + capped]
    items = [{
        "id": eid,
        "type": etype,
        "name": display_name(attrs, eid),
        "attributes": attrs or {},
        "sources": by_entity.get(eid, []),
    } for eid, etype, attrs in page]
    return {"type": ontology_type, "total": total,
            "offset": start, "limit": capped, "items": items}


def graph_view(entities, relationships) -> dict[str, Any]:
    """Type-level knowledge map: nodes per type, edges aggregated by relation.

    Renders the *shape* of the graph (Customer -HAS_SITE(22)-> Site ...) rather
    than every node — legible at any scale, the query-don't-render rule.
    """
    entities = list(entities)
    relationships = list(relationships)
    id_type = {eid: etype for eid, etype, _ in entities}
    type_counts = Counter(etype for _, etype, _ in entities)
    edge_agg: Counter = Counter()
    for src, tgt, name in relationships:
        st, tt = id_type.get(src), id_type.get(tgt)
        if st and tt:
            edge_agg[(st, tt, name)] += 1
    return {
        "type_nodes": [{"type": t, "count": c}
                       for t, c in type_counts.most_common()],
        "type_edges": [{"source": s, "target": t, "name": n, "count": c}
                       for (s, t, n), c in edge_agg.most_common()],
        "entity_count": len(entities),
        "relationship_count": len(relationships),
    }


def _normalise_text(text: str) -> str:
    """Lowercase + split camel case so brief text can match ontology labels."""
    split = _CAMEL_RE.sub(" ", str(text or ""))
    return " ".join(part.lower() for part in _WORD_RE.findall(split))


def _tokens(text: str) -> set[str]:
    """Tokenise a label, dropping tiny/common words that drown the match signal."""
    return {
        tok for tok in _normalise_text(text).split()
        if (len(tok) > 1 or tok.isdigit()) and tok not in _STOPWORDS
    }


def _matches(query_text: str, candidate: str) -> bool:
    """Return True when text overlaps by phrase or meaningful token."""
    q_norm = _normalise_text(query_text)
    c_norm = _normalise_text(candidate)
    if not q_norm or not c_norm:
        return False
    if _tokens(query_text) & _tokens(candidate):
        return True
    return len(q_norm) >= 4 and len(c_norm) >= 4 and (q_norm in c_norm or c_norm in q_norm)


def _entity_match_text(entity_id: int, entity_type: str, attrs: dict[str, Any]) -> str:
    """Build a compact text block used to decide if an entity matches the brief."""
    parts = [entity_type, display_name(attrs or {}, entity_id)]
    for value in (attrs or {}).values():
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(parts)


def _domain_matches(
    entities: list[tuple[int, str, dict[str, Any]]], query_text: str,
) -> tuple[set[int], set[str]]:
    """Match the query against entity types first, then against entity text."""
    if not _tokens(query_text):
        return set(), set()

    ids_by_type: dict[str, set[int]] = defaultdict(set)
    for entity_id, entity_type, _attrs in entities:
        ids_by_type[entity_type].add(entity_id)

    matched_types = {
        entity_type for entity_type in ids_by_type
        if _matches(query_text, entity_type)
    }
    matched_ids = {
        entity_id for entity_type in matched_types
        for entity_id in ids_by_type[entity_type]
    }

    for entity_id, entity_type, attrs in entities:
        if _matches(query_text, _entity_match_text(entity_id, entity_type, attrs or {})):
            matched_ids.add(entity_id)
            matched_types.add(entity_type)

    return matched_ids, matched_types


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
