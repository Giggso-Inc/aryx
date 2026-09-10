"""Match-key selectivity check for the entity-resolution funnel.

Split out of `resolve_entities.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03) — the one function in that module with zero `get_settings()`
dependency and no patch exposure of its own (confirmed via grep). See
`resolve_entities.py`'s docstring for why the rest of the module stays put.
"""
from __future__ import annotations

from aryx.models import ResolutionRecord


def _key_selectivity(records: list[ResolutionRecord], sample_size: int) -> float:
    """Distinct-value ratio of match text over a bounded sample.

    A cheap, upfront signal for whether the match key has enough identity
    information to produce a meaningful block at all — the same principle
    already applied to FK-detection candidates (dynamic_fk.py) applied one
    layer over: measure selectivity before committing to expensive work,
    not after discovering it was pointless.
    """
    sample = records[:sample_size]
    if not sample:
        return 1.0
    distinct = len({r.text.strip().lower() for r in sample if r.text})
    return distinct / len(sample)
