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
from aryx.config import get_settings
from aryx.graph.reader import GraphReader

__all__ = ["RetrievedEntity", "all_types", "gather", "render_context", "retrieve"]

# Identifier-shape heuristic for the attribute-value lookup fallback — a term
# "looks like an identifier" if it's a single alphanumeric run (no spaces) at
# least identifier_min_length characters long AND contains at least one
# digit. The digit requirement keeps this a COST gate rather than a
# vocabulary check: real-world identifiers (NSN, FSC, PR#, SKUs) always mix
# in digits, while ordinary English words never need to. This never names a
# field/column; it only decides whether the (more expensive) attribute-value
# scan is worth attempting at all, purely from the shape of the SEARCH TERM.
_IDENTIFIER_SHAPE_RE = re.compile(r"^[A-Za-z0-9]+$")


def _looks_like_identifier(term: str) -> bool:
    min_len = get_settings().identifier_min_length
    return (
        len(term) >= min_len
        and bool(_IDENTIFIER_SHAPE_RE.match(term))
        and any(ch.isdigit() for ch in term)
    )


def all_types(reader: GraphReader) -> list[str]:
    """Distinct ontology types present — helps the parser pick search terms."""
    return sorted({e["type"] for e in reader.find_entities(limit=500)})


def _lookup(reader: GraphReader, term: str) -> tuple[list[dict], list[str]]:
    """Find entities for a term.

    Tries in order:
    (1) Numeric id lookup ('378' -> entity id=378). Needed because
        pipeline-derived entity names are often a non-id column (e.g.
        ticket.status='open'), so plain name search misses 'ticket 378'.
    (2) Substring name match on the term as-is.
    (3) Longest-word fallback for multi-word phrases.
    (4) Attribute-value fallback, tried only when (1)-(3) all miss AND the
        term looks identifier-shaped: an entity's e.name is chosen from a
        single hardcoded priority list (aryx.explore._NAME_KEYS), so a row
        with several equally-real identifiers (FSC, NSN, PR#, ...) is only
        ever findable by whichever one won that list. This matches against
        ANY property instead — see GraphReader.find_entity_by_attribute_
        value's docstring for why this stays dynamic (no field/column names
        anywhere) and why it's last.

    Returns:
        (hits, extra_calls) — extra_calls records any fallback beyond the
        term-shape-based logging gather() already does up front, so the
        Sources/audit trail shows exactly which path found the answer.
    """
    calls: list[str] = []
    digits = "".join(ch for ch in term if ch.isdigit())
    if digits and len(digits) <= 9:
        ent = reader.get_entity(int(digits))
        if ent:
            return [ent], calls
    hits = reader.find_entities(name=term, limit=5)
    if not hits and " " in term:
        for word in sorted(term.split(), key=len, reverse=True):
            if len(word) > 2 and not word.isdigit():
                hits = reader.find_entities(name=word, limit=5)
                if hits:
                    break

    if not hits and get_settings().identifier_lookup_enabled and _looks_like_identifier(term):
        calls.append(f"find_by_attribute_value(value={term!r})")
        hits = reader.find_entity_by_attribute_value(
            term, limit=get_settings().identifier_lookup_limit)

    return hits, calls


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
        hits, extra_calls = _lookup(reader, term)
        calls.extend(extra_calls)
        for ent in hits:
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


def render_context(entities: list[RetrievedEntity]) -> str:
    """Project structured entities into the compact text the LLM reads."""
    blocks: list[str] = []
    for ent in entities:
        lines = [f"{ent.name} [{ent.type}] (id {ent.id})"]
        for n in ent.neighbors:
            arrow = "->" if n["direction"] == "out" else "<-"
            lines.append(f"  {arrow} {n['relationship']} {n['name']} [{n['type']}]")
        if ent.sources:
            srcs = ", ".join(f"{p['system']}.{p['dataset']}" for p in ent.sources)
            lines.append(f"  source: {srcs}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else "No matching entities in the graph."


def retrieve(reader: GraphReader, terms: list[str]) -> tuple[str, list[str]]:
    """Back-compat wrapper: structured gather projected to (context, calls)."""
    entities, calls = gather(reader, terms)
    return render_context(entities), calls
