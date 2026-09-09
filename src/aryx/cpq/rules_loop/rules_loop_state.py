"""Mutable/read-only state for ``evaluate_rules_loop``'s per-pass split
(Phase 4, one of the 8 previously-deferred oversized `CpqEngine`
methods, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Every field on `LoopState` was a plain local the original single-
function loop body carried across its up-to-8 passes (one Python call,
so a bare local already survived pass to pass — this dataclass changes
nothing about that lifecycle, just gives the passed-around bundle a
name once the loop body moved to sibling modules). `LoopScope` is the
read-only per-call configuration every pass needs but never mutates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LoopState:
    """Mutated in place, pass over pass, by both pass-step modules."""

    attrs: list[Any]
    filled: dict[str, str]
    display_filled: dict[str, str]
    sources: dict[str, str]
    multi: dict[str, list[str]]
    dropped: dict[str, list[str]]
    constrained_opts: dict[int, list[str]] = field(default_factory=dict)
    dt_cache: dict[tuple[int, str], tuple] = field(default_factory=dict)
    default_fill_signatures: dict[str, tuple] = field(default_factory=dict)
    constraint_cache: dict[str, tuple] = field(default_factory=dict)
    oscillating_vns: set[str] = field(default_factory=set)
    last_inconsistent_vns: frozenset[str] = frozenset()
    last_resync_vns: frozenset[str] = frozenset()
    # Per-pass scratch, reset at the top of every pass by run_early_pass:
    prev_filled_keys: set[str] = field(default_factory=set)
    prev_visible_ids: set[int] = field(default_factory=set)
    inconsistent_vns: frozenset[str] = frozenset()
    resynced: dict[str, tuple[str, str]] = field(default_factory=dict)
    pass_t0: float = 0.0


@dataclass(frozen=True)
class LoopScope:
    """Read-only per-`evaluate_rules_loop`-call configuration."""

    hints: dict[str, str]
    hiding_rules: list[Any]
    rec_rules: list[Any]
    con_rules: list[Any]
    bml_eval: Any | None
    country: str | None
    negated_vns: set[str] | None
    skip_always_ask: set[str] | None
    display_order: dict[str, int] | None
    workspace_id: int | None
    catalog_prefix: str
