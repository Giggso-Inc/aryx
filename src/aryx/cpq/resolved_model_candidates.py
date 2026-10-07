"""CPQModel candidates with the turn's resolved model first.

Shared by the D8 (inferred legal values) and D10 (derive base model) ports.
Mirrors aryxent PR 9: ``model_resolution``'s resolved ``chosen.cpq_model``
is tried ahead of the product-derived candidate list; duplicates dropped.
Absent a resolved turn, only the product-derived candidates are returned.
"""
from __future__ import annotations

from aryx.cpq import model_resolution as _model_resolution
from aryx.cpq.data_table.model_key_map import front_mapped_key
from aryx.cpq.data_table_bridge.candidates import _cpq_model_candidates


def resolved_model_first_candidates(
    product: str, workspace_id: int, catalog_prefix: str,
    cache: dict[tuple[int, str], tuple] | None, base_model: str = "",
) -> list[str]:
    """Ordered, de-duplicated candidate CPQModels for this turn."""
    ctx = _model_resolution.get_turn()
    resolved: tuple[str, ...] = ()
    if ctx is not None and ctx.resolution.resolved and ctx.resolution.chosen is not None:
        resolved = (ctx.resolution.chosen.cpq_model,)
    fallback = (
        _cpq_model_candidates(product, workspace_id, catalog_prefix, cache, base_model=base_model)
        if product else ()
    )
    seen: set[str] = set()
    ordered: list[str] = []
    for cpq_model in (*resolved, *fallback):
        if cpq_model not in seen:
            seen.add(cpq_model)
            ordered.append(cpq_model)
    return list(front_mapped_key(tuple(ordered), product, workspace_id, catalog_prefix, cache))
