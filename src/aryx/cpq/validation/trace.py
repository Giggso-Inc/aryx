"""Complete-state fingerprints and compact deterministic iteration traces."""
from __future__ import annotations

from typing import Any


def state_fingerprint(
    filled: dict[str, str], filled_multi: dict[str, tuple[str, ...]],
    sources: dict[str, str], hidden: frozenset[str],
    constraints: dict[str, tuple[str, ...]], pending: tuple[str, ...],
    unknown: tuple[str, ...],
) -> tuple[Any, ...]:
    """Capture every state dimension that can affect convergence."""
    return (
        tuple(sorted(filled.items())), tuple(sorted(sources.items())),
        tuple((key, filled_multi[key]) for key in sorted(filled_multi)),
        tuple(sorted(hidden)),
        tuple((key, constraints[key]) for key in sorted(constraints)),
        pending, unknown,
    )


def trace_entry(
    iteration: int, filled: dict[str, str],
    filled_multi: dict[str, tuple[str, ...]], hidden: frozenset[str],
    constraints: dict[str, tuple[str, ...]], pending: tuple[str, ...],
    unknown: tuple[str, ...],
) -> dict[str, Any]:
    """Capture a compact, stable reproduction trace for one pass."""
    return {
        "iteration": iteration,
        "filled": dict(sorted(filled.items())),
        "filled_multi": {key: list(filled_multi[key]) for key in sorted(filled_multi)},
        "hidden": sorted(hidden),
        "constraints": {key: list(constraints[key]) for key in sorted(constraints)},
        "pending": list(pending),
        "unknown_rules": list(unknown),
    }
