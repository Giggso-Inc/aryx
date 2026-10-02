"""Derive the Base Model option from already-known attribute values (D10).

Port of aryxent PR 8: before the Base Model attr falls through to its
full raw-list always-ask anchor, narrow the model's real base models to
exactly one using Whitelist evidence from the attrs known this turn.
Gated by ``cpq_derive_base_model_enabled``; never guesses among 2+.
"""
from __future__ import annotations

import logging

from aryx.config import get_settings
from aryx.cpq.data_table.data_table_derive_base_model import derive_base_model_from_known_attrs
from aryx.cpq.logging_context import install_run_id_logging
from aryx.cpq.resolved_model_candidates import resolved_model_first_candidates
from aryx.cpq.state import MenuOption

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)


def derived_base_model_option(
    options: list[MenuOption], filled: dict[str, str],
    workspace_id: int | None, catalog_prefix: str,
    cache: dict[tuple[int, str], tuple] | None,
) -> MenuOption | None:
    """The Base Model option derived from `filled`, or None (flag off / no
    workspace / no options / not narrowed to one real option). Never raises."""
    if workspace_id is None or not options:
        return None
    if not get_settings().cpq_derive_base_model_enabled:
        return None
    try:
        product = filled.get("productSelectionProduct_all", "")
        for cpq_model in resolved_model_first_candidates(product, workspace_id, catalog_prefix, cache):
            derived = derive_base_model_from_known_attrs(
                cpq_model, filled, workspace_id, catalog_prefix, cache,
            )
            if derived is None:
                continue
            match = next((o for o in options if o.item_value == derived), None)
            if match is not None:
                logger.info("cpq: derived_base_model cpq_model=%r derived=%r", cpq_model, derived)
                return match
    except Exception:  # noqa: BLE001 -- derivation must never break the fill pass
        logger.exception("cpq: derive base model failed")
    return None
