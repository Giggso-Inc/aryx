"""Deterministic graph retrieval for the Ask flow.

Small local models are unreliable at free-form tool-calling, so retrieval is
driven here and the LLM only interprets the question and writes the answer.
Each graph call is recorded so the UI can show exactly what was queried.

Retrieval gathers *structured* entity records (``gather``); the text context
the LLM reads and the grounding record the Accuracy Lab verifies are both
projected from that same structure, so the answer and its provenance can never
drift apart.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`retrieve_lookup.py` (`all_types`/`_lookup`) and `retrieve_context.py`
(`render_context`), both re-imported here. Zero whitebox test patches
exist anywhere against `aryx.graph.retrieve.*` (confirmed via grep), so
the split was purely mechanical. `gather`/`retrieve` stay here as the
entry points tying lookup + rendering together.
"""
from __future__ import annotations

from aryx.ask.evidence import RetrievedEntity
from aryx.graph.reader import GraphReader
from aryx.graph.retrieve_context import render_context
from aryx.graph.retrieve_lookup import _lookup, _types_cache, all_types

__all__ = ["RetrievedEntity", "_types_cache", "all_types", "gather", "render_context", "retrieve"]


def gather(reader: GraphReader, terms: list[str]) -> tuple[list[RetrievedEntity], list[str]]:
    """Look up terms, expand one hop, gather provenance — as structured records.

    docs/FALKORDB_QUERY_EXHAUSTION_2026_08_14.md — neighbors() used to run
    once per matched entity (confirmed live: 50-100+ Cypher calls for one
    /ask). Now batched via neighbors_batch(): one round trip for every
    entity this call matched, logged as a single get_neighbors_batch(...)
    entry instead of one get_neighbors(eid) line per entity — the log stays
    literal (this module's own docstring above: "the UI can show exactly
    what was queried"), it just reflects the real, smaller number of round
    trips. provenance() has no batch form yet, so it's still one call per
    entity.

    Returns the deduplicated entities and the exact graph calls made.
    """
    calls: list[str] = []
    seen: set[int] = set()
    hits: list[dict] = []

    for term in terms[:5]:
        digits = "".join(ch for ch in term if ch.isdigit())
        if digits and len(digits) <= 9:
            calls.append(f"get_entity(id={int(digits)})")
        else:
            calls.append(f"search_entities(name={term!r})")
        for ent in _lookup(reader, term):
            eid = ent["id"]
            if eid in seen:
                continue
            seen.add(eid)
            hits.append(ent)

    eids = [h["id"] for h in hits]
    neighbor_map: dict[int, list[dict]] = {}
    if eids:
        calls.append(f"get_neighbors_batch({eids})")
        neighbor_map = reader.neighbors_batch(eids)

    out: list[RetrievedEntity] = []
    for ent in hits:
        eid = ent["id"]
        calls.append(f"get_provenance({eid})")
        sources = reader.provenance(eid)
        out.append(RetrievedEntity(id=eid, type=ent["type"], name=ent["name"],
                                   neighbors=neighbor_map.get(eid, []), sources=sources))
    return out, calls


def retrieve(reader: GraphReader, terms: list[str]) -> tuple[str, list[str]]:
    """Back-compat wrapper: structured gather projected to (context, calls)."""
    entities, calls = gather(reader, terms)
    return render_context(entities), calls
