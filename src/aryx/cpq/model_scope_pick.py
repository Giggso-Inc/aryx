"""Model-scoped "first available option" for the blind-pick sites.

The blind first-by-order picks (``tier6_single_b``, ``ask_data_gap``,
``ask_rule_governed_blind``) take ``options[0]`` of the catalog menu, which
may be illegal for the model the quote is actually for. When
``cpq_model_scope_lookups_enabled`` is on and the turn has a resolved model
(``model_resolution``), ``scoped_first_available`` returns the first option,
in the same catalog order, that the model's own Whitelist allows. Ported from
aryxent ``_diag_model_scope_first_available`` (PR 3). With the flag off, no
resolved model, or no legal option found it returns None so the caller keeps
its original pick untouched.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.config import get_settings
from aryx.cpq import model_resolution as _model_resolution
from aryx.cpq.catalog_profile import resolve_base_model_vn
from aryx.cpq.data_table.data_table_resolver import (
    resolve_whitelist_values as dt_resolve_whitelist_values,
)
from aryx.cpq.logging_context import install_run_id_logging
from aryx.cpq.state import MenuOption

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)


def scoped_first_available(
    vn: str, valid_opts: list[MenuOption], filled: dict[str, str],
    workspace_id: int | None, catalog_prefix: str,
    cache: dict[tuple[int, str], tuple] | None,
) -> MenuOption | None:
    """The first of ``valid_opts`` legal for the turn's resolved model, or
    None (flag off / unresolved turn / no legal set / no legal option).

    The base model is used only when it is one of the model's own; otherwise
    only the model's ``BaseModel="ALL"`` rows apply. Never raises.
    """
    if workspace_id is None or not valid_opts:
        return None
    if not get_settings().cpq_model_scope_lookups_enabled:
        return None
    ctx = _model_resolution.get_turn()
    if ctx is None or not ctx.resolution.resolved or ctx.resolution.chosen is None:
        return None
    chosen = ctx.resolution.chosen
    base_model = filled.get(
        resolve_base_model_vn(filled, workspace_id, catalog_prefix, cache), "")
    scoped_base_model = base_model if base_model in chosen.base_models else ""
    try:
        legal: Any = dt_resolve_whitelist_values(
            chosen.cpq_model, scoped_base_model, vn, filled,
            workspace_id, catalog_prefix, cache,
        )
    except Exception:  # noqa: BLE001 -- scoping must never break the fill pass
        logger.exception("cpq: model_scope pick lookup failed vn=%r", vn)
        return None
    scoped = next((o for o in valid_opts if legal and o.item_value in legal), None)
    if scoped is not None and scoped.item_value != valid_opts[0].item_value:
        if ctx.first_time(("pick", vn, valid_opts[0].item_value, scoped.item_value)):
            logger.info(
                "cpq: model_scope picked vn=%r current=%r scoped=%r model=%r "
                "base_model=%r legal=%r",
                vn, valid_opts[0].item_value, scoped.item_value,
                chosen.cpq_model, scoped_base_model or "(ALL rows only)", legal,
            )
    return scoped
