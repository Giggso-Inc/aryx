"""Whitelist narrowing for grid-quantity pending (D17).

Port of aryxent's ``resolve_pending_grid_quantities`` fallback: when a
not-yet-selected grid selector has no ``constrained_opts`` entry, use the
Data Table's Whitelist-narrowed legal set so quantity questions are not
asked for options illegal for the model. Gated by
``cpq_whitelist_narrow_questions_enabled``.
"""

from __future__ import annotations

from typing import Any

from aryx.config import get_settings


def grid_narrow_kwargs(
    workspace_id: int | None, catalog_prefix: str = "",
    dt_cache: dict[tuple, Any] | None = None,
) -> dict[str, Any]:
    """Extra kwargs for ``append_pending_grid_quantities`` call sites: the
    workspace/catalog (and the caller's per-turn `dt_cache`, so the Whitelist
    index is built once, not per selector/candidate) when the flag is on,
    else ``{}`` (call unchanged)."""
    if workspace_id is None or not get_settings().cpq_whitelist_narrow_questions_enabled:
        return {}
    kwargs: dict[str, Any] = {"workspace_id": workspace_id, "catalog_prefix": catalog_prefix}
    if dt_cache is not None:
        kwargs["dt_cache"] = dt_cache
    return kwargs


def whitelist_narrowed_selector_options(
    selector_vn: str, filled: dict[str, str], workspace_id: int | None,
    catalog_prefix: str, dt_cache: dict[tuple[int, str], tuple] | None,
) -> list[str] | None:
    """Whitelist-narrowed legal values for the selector, or None (flag off /
    no workspace / no table coverage)."""
    if workspace_id is None or not get_settings().cpq_whitelist_narrow_questions_enabled:
        return None
    from aryx.cpq.data_table_bridge.conflicts import _resolve_narrowed_legal_values

    return _resolve_narrowed_legal_values(
        selector_vn, filled, workspace_id, catalog_prefix, dt_cache,
    )
