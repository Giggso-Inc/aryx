"""Backend-agnostic data shapes for the raw-graph projection.

Kept dependency-free (no FalkorDB/Oracle imports) so ``xml_projector`` stays
a pure function, unit-testable without any live store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RawNode:
    """One XML element projected to one raw graph node."""

    id: int
    tag: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawEdge:
    """One parent-element -> child-element nesting relationship."""

    source_id: int
    target_id: int
    name: str


@dataclass(frozen=True, slots=True)
class RawGraphProjection:
    """The full set of nodes/edges produced by walking one XML document."""

    nodes: list[RawNode]
    edges: list[RawEdge]


@dataclass(frozen=True, slots=True)
class RawGraphWriteResult:
    """Summary of a raw-graph write, for progress reporting and tests."""

    nodes_written: int
    edges_written: int
    backend: str
    graph_ref: str
