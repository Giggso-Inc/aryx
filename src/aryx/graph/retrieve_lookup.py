"""Entity type listing (TTL-cached) and term-to-entity lookup for graph retrieval.

Split out of `graph/retrieve.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import re
import time

from aryx.graph.reader import GraphReader

# Module-level TTL cache for all_types() — one entry per graph name.
# all_types() runs on nearly every /ask call (fast attribute-options path is
# the only one that skips it), but entity types only change on ingestion, not
# per question, so a short TTL collapses repeated calls to 0 queries.
_types_cache: dict[str, tuple[float, list[str]]] = {}
_TYPES_TTL: float = 30.0


def all_types(reader: GraphReader) -> list[str]:
    """Distinct ontology types present — helps the parser pick search terms.

    Uses reader.distinct_types() (a single `RETURN DISTINCT e.type` query)
    rather than find_entities(limit=500), which ran a 500-row MATCH scan
    returning the full properties() map per row just to read off `type` --
    500x more data transfer than this needs.
    """
    cache_key = reader.graph_name
    now = time.monotonic()
    cached = _types_cache.get(cache_key)
    if cached is not None:
        ts, types = cached
        if now - ts < _TYPES_TTL:
            return types
    types = sorted(reader.distinct_types())
    _types_cache[cache_key] = (now, types)
    return types


def _lookup(reader: GraphReader, term: str) -> list[dict]:
    """Find entities for a term.

    Tries in order:
    (1) Numeric id lookup ('378' -> entity id=378).
    (2) Substring name match on the term as-is.
    (3) Longest-word fallback for multi-word phrases.
    (4) Compressed fallback: strip non-alphanumeric chars so that
        "APX NEXT" matches entity names like "aPXNext_BOM" — necessary
        when XML attribute values use camelCase+underscores while question
        terms use space-separated words.
    """
    digits = "".join(ch for ch in term if ch.isdigit())
    if digits and len(digits) <= 9:
        ent = reader.get_entity(int(digits))
        if ent:
            return [ent]
    hits = reader.find_entities(name=term, limit=5)
    if not hits and " " in term:
        for word in sorted(term.split(), key=len, reverse=True):
            if len(word) > 2 and not word.isdigit():
                hits = reader.find_entities(name=word, limit=5)
                if hits:
                    break

    # Always also try the compressed form (non-alphanumeric chars stripped).
    # "APX NEXT" compresses to "APXNEXT" which matches entity names like
    # "aPXNext_BOM" even when the space-separated form already found different
    # entities (e.g. BmMenuItems named "APX NEXT Single Band").  Merging both
    # result sets ensures catalog/root entities are included alongside leaf nodes.
    compressed = re.sub(r"[^a-zA-Z0-9]", "", term)
    if compressed and compressed.lower() != term.lower() and len(compressed) > 2:
        existing_ids = {h["id"] for h in hits}
        for h in reader.find_entities(name=compressed, limit=5):
            if h["id"] not in existing_ids:
                hits.append(h)
                existing_ids.add(h["id"])

    return hits
