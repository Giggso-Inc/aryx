"""Tests for render_context() truncation and edge-case behaviour.

Covers: normal path, neighbor cap, sources cap, first-entity overflow guard,
multi-entity drop signal, and empty input.
"""
from __future__ import annotations

from aryx.ask.evidence import RetrievedEntity
from aryx.graph.retrieve import render_context


def _ent(
    eid: int,
    name: str,
    neighbors: list[dict] | None = None,
    sources: list[dict] | None = None,
) -> RetrievedEntity:
    return RetrievedEntity(
        id=eid,
        type="Product",
        name=name,
        neighbors=neighbors or [],
        sources=sources or [],
    )


def _nbr(name: str, direction: str = "out") -> dict:
    return {"name": name, "type": "Component", "relationship": "HAS", "direction": direction}


def _src(system: str = "sf", dataset: str = "Account") -> dict:
    return {"system": system, "dataset": dataset, "record_id": "x"}


# ---------------------------------------------------------------------------
# Normal path
# ---------------------------------------------------------------------------

def test_single_entity_renders_name_type_id() -> None:
    result = render_context([_ent(1, "Acme")])
    assert "Acme [Product] (id 1)" in result


def test_empty_returns_no_matching_message() -> None:
    assert render_context([]) == "No matching entities in the graph."


# ---------------------------------------------------------------------------
# Neighbor cap
# ---------------------------------------------------------------------------

def test_neighbors_capped_at_max_neighbors() -> None:
    nbrs = [_nbr(f"N{i}") for i in range(20)]
    result = render_context([_ent(1, "X", neighbors=nbrs)], max_neighbors=5)
    assert "15 more relationships truncated" in result
    # Only 5 neighbour lines rendered (each starts with "  ->")
    rendered_nbrs = [ln for ln in result.splitlines() if ln.startswith("  ->")]
    assert len(rendered_nbrs) == 5


def test_neighbors_within_cap_has_no_truncation_note() -> None:
    nbrs = [_nbr(f"N{i}") for i in range(3)]
    result = render_context([_ent(1, "X", neighbors=nbrs)], max_neighbors=5)
    assert "truncated" not in result


# ---------------------------------------------------------------------------
# Sources cap
# ---------------------------------------------------------------------------

def test_sources_capped_at_max_sources() -> None:
    srcs = [_src(f"sys{i}", "ds") for i in range(8)]
    result = render_context([_ent(1, "X", sources=srcs)], max_sources=5)
    assert "(+3 more)" in result


def test_sources_within_cap_has_no_overflow_note() -> None:
    srcs = [_src(f"sys{i}", "ds") for i in range(3)]
    result = render_context([_ent(1, "X", sources=srcs)], max_sources=5)
    assert "more)" not in result


# ---------------------------------------------------------------------------
# First-entity overflow guard
# ---------------------------------------------------------------------------

def test_first_entity_exceeds_max_chars_returns_truncated_not_no_match() -> None:
    """A single very large entity must not produce 'No matching entities'."""
    big_name = "A" * 500
    result = render_context([_ent(1, big_name)], max_chars=100)
    assert result != "No matching entities in the graph."
    assert big_name[:50] in result  # truncated block still starts with the name


def test_first_entity_overflow_result_length_at_most_max_chars() -> None:
    big_name = "B" * 2000
    result = render_context([_ent(1, big_name)], max_chars=200)
    # The first block is sliced to max_chars; the rest may add the drop signal
    assert len(result) <= 200 + 100  # small tolerance for the drop note


# ---------------------------------------------------------------------------
# Multi-entity drop signal
# ---------------------------------------------------------------------------

def test_dropped_entities_signal_appended() -> None:
    ents = [_ent(i, f"Ent{i}") for i in range(10)]
    result = render_context(ents, max_chars=50)
    assert "additional" in result and "omitted" in result


def test_no_drop_signal_when_all_fit() -> None:
    ents = [_ent(1, "Short"), _ent(2, "Also")]
    result = render_context(ents, max_chars=10_000)
    assert "omitted" not in result


def test_drop_signal_uses_singular_noun_for_one_dropped() -> None:
    # Two entities; second is big enough to push total over cap
    ent1 = _ent(1, "Small")
    ent2 = _ent(2, "X" * 500)
    result = render_context([ent1, ent2], max_chars=len("Small [Product] (id 1)") + 5)
    assert "1 additional entity omitted" in result


def test_drop_signal_uses_plural_noun_for_multiple_dropped() -> None:
    ent1 = _ent(1, "S")
    others = [_ent(i, f"Big{'X' * 200}") for i in range(2, 5)]
    result = render_context([ent1] + others, max_chars=30)
    assert "entities omitted" in result
