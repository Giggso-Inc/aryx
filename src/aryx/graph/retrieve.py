"""Deterministic graph retrieval for the Ask flow.

Small local models are unreliable at free-form tool-calling, so retrieval is
driven here and the LLM only interprets the question and writes the answer.
Each graph call is recorded so the UI can show exactly what was queried.

Retrieval gathers *structured* entity records (``gather``); the text context
the LLM reads and the grounding record the Accuracy Lab verifies are both
projected from that same structure, so the answer and its provenance can never
drift apart.
"""
from __future__ import annotations

import re
from typing import Any

from aryx.ask.evidence import RetrievedEntity
from aryx.graph.reader import GraphReader

__all__ = ["RetrievedEntity", "all_types", "gather", "render_context", "retrieve"]


def all_types(reader: GraphReader) -> list[str]:
    """Distinct ontology types present — helps the parser pick search terms."""
    return sorted({e["type"] for e in reader.find_entities(limit=500)})


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


def gather(reader: GraphReader, terms: list[str]) -> tuple[list[RetrievedEntity], list[str]]:
    """Look up terms, expand one hop, gather provenance — as structured records.

    Returns the deduplicated entities and the exact graph calls made.
    """
    calls: list[str] = []
    seen: set[int] = set()
    out: list[RetrievedEntity] = []

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
            calls.append(f"get_neighbors({eid})")
            neighbors = reader.neighbors(eid)
            calls.append(f"get_provenance({eid})")
            sources = reader.provenance(eid)
            out.append(RetrievedEntity(id=eid, type=ent["type"], name=ent["name"],
                                       neighbors=neighbors, sources=sources))
    return out, calls


def render_context(
    entities: list[RetrievedEntity],
    max_neighbors: int = 15,
    max_sources: int = 5,
    max_chars: int = 12_000,
) -> str:
    """Project structured entities into the compact text the LLM reads.

    Caps neighbors per entity, sources per entity, and total context size so
    that large graphs (tens of thousands of entities) do not produce prompts
    that exceed the model's effective context window and cause multi-minute
    inference times.
    """
    # Keys that are internal bookkeeping — never helpful to the LLM.
    _SKIP_ATTR_KEYS = frozenset({
        "id", "_element_type", "name", "guid", "date_modified",
        "last_update_date", "last_updated_by", "last_update_login",
    })
    # Values that carry no information.
    _TRIVIAL_VALS = frozenset({"0", "1", "", "null", "none", "unknown"})
    # Neighbor entity TYPES that are internal BML rule constructs (hiding/
    # recommendation/constraint/validation rules — BigMachines' own
    # BmConfigRule, ingested per-catalog with a type prefix e.g.
    # "ApxNextConfigBmConfigRule") — never customer-facing facts, but
    # confirmed live to leak straight into an answer verbatim ("Hide Model
    # selection frequency band attribute", "Associated Recommendation
    # Rule") because this neighbor listing had no type filter at all, only
    # _SKIP_ATTR_KEYS for an entity's OWN attributes. Suffix match (not
    # exact), same catalog-prefix-agnostic convention used elsewhere in
    # this codebase (e.g. CpqEngine._attr_index).
    _INTERNAL_NEIGHBOR_TYPE_SUFFIXES = ("bmconfigrule",)

    def _is_internal_rule_neighbor(neighbor_type: str) -> bool:
        t = (neighbor_type or "").lower()
        return any(t.endswith(suffix) for suffix in _INTERNAL_NEIGHBOR_TYPE_SUFFIXES)

    blocks: list[str] = []
    total = 0
    for ent in entities:
        lines = [f"{ent.name} [{ent.type}] (id {ent.id})"]
        # Include meaningful entity attributes so the LLM has real content.
        if ent.attributes:
            attr_lines: list[str] = []
            for k, v in ent.attributes.items():
                if k in _SKIP_ATTR_KEYS:
                    continue
                vs = str(v).strip()
                if not vs or vs.lower() in _TRIVIAL_VALS or len(vs) > 300:
                    continue
                attr_lines.append(f"  {k}: {vs}")
                if len(attr_lines) >= 12:
                    break
            lines.extend(attr_lines)
        _visible_neighbors = [
            n for n in ent.neighbors if not _is_internal_rule_neighbor(n.get("type", ""))
        ]
        for n in _visible_neighbors[:max_neighbors]:
            arrow = "->" if n["direction"] == "out" else "<-"
            lines.append(f"  {arrow} {n['relationship']} {n['name']} [{n['type']}]")
        if len(_visible_neighbors) > max_neighbors:
            lines.append(f"  ... ({len(_visible_neighbors) - max_neighbors} more relationships truncated)")
        if ent.sources:
            capped = ent.sources[:max_sources]
            srcs = ", ".join(f"{p['system']}.{p['dataset']}" for p in capped)
            if len(ent.sources) > max_sources:
                srcs += f" (+{len(ent.sources) - max_sources} more)"
            lines.append(f"  source: {srcs}")
        block = "\n".join(lines)
        if total + len(block) > max_chars:
            if not blocks:
                # First entity alone exceeds budget — include it truncated so
                # we never return a misleading "no matching entities" result
                # when a real match exists but is too large to fit whole.
                blocks.append(block[:max_chars])
            break
        blocks.append(block)
        total += len(block) + 2  # +2 for the "\n\n" join separator

    if not blocks:
        return "No matching entities in the graph."

    result = "\n\n".join(blocks)
    dropped = len(entities) - len(blocks)
    if dropped:
        noun = "entity" if dropped == 1 else "entities"
        result += f"\n\n[{dropped} additional {noun} omitted — context size limit reached]"
    return result


def retrieve(reader: GraphReader, terms: list[str]) -> tuple[str, list[str]]:
    """Back-compat wrapper: structured gather projected to (context, calls)."""
    entities, calls = gather(reader, terms)
    return render_context(entities), calls
