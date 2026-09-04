"""Union-find clustering of overlapping dimension-column candidates.

Split out of `pipeline/dimension_link.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Calls no `get_settings()` and is never itself
patched — zero patch risk, confirmed via grep.
"""
from __future__ import annotations

from collections import defaultdict

from aryx.pipeline.dimension_link_columns import CandidateKey, ValueMap


def _find(parent: dict[CandidateKey, CandidateKey], key: CandidateKey) -> CandidateKey:
    while parent[key] != key:
        parent[key] = parent[parent[key]]
        key = parent[key]
    return key


def _union(parent: dict[CandidateKey, CandidateKey], a: CandidateKey, b: CandidateKey) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[ra] = rb


def _dimension_groups(
    candidates: dict[CandidateKey, ValueMap], min_overlap: float, min_types: int,
) -> list[list[CandidateKey]]:
    """Cluster (type, col) candidates whose value sets overlap sufficiently,
    across DIFFERENT types only, keeping only groups spanning >= min_types
    distinct ontology types."""
    keys = list(candidates.keys())
    parent: dict[CandidateKey, CandidateKey] = {k: k for k in keys}
    for i in range(len(keys)):
        type_a, _ = keys[i]
        values_a = set(candidates[keys[i]].keys())
        if not values_a:
            continue
        for j in range(i + 1, len(keys)):
            type_b, _ = keys[j]
            if type_a == type_b:
                continue
            values_b = set(candidates[keys[j]].keys())
            if not values_b:
                continue
            overlap = len(values_a & values_b) / min(len(values_a), len(values_b))
            if overlap >= min_overlap:
                _union(parent, keys[i], keys[j])

    groups: dict[CandidateKey, list[CandidateKey]] = defaultdict(list)
    for k in keys:
        groups[_find(parent, k)].append(k)
    return [g for g in groups.values() if len({etype for etype, _ in g}) >= min_types]
