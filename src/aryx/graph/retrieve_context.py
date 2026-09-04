"""Project structured retrieved entities into the compact text the LLM reads.

Split out of `graph/retrieve.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

from aryx.ask.evidence import RetrievedEntity


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
