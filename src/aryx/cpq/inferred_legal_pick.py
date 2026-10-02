"""Inferred-legal-values pick for the blind first-available sites (D8).

After ``scoped_first_available`` finds nothing (Whitelist never declares this
attribute's legal set for the model), infer a legal set from the Whitelist's
condition-column evidence (``infer_implied_legal_values``) and take the
lowest-order real option inside it. Gated by
``cpq_infer_legal_values_enabled``; flag off / no evidence -> None so the
caller keeps its raw first option. Ported from aryxent
``_resolve_via_inferred_legal_values`` (PR 7/9/15).
"""
from __future__ import annotations

import logging

from aryx.config import get_settings
from aryx.cpq.data_table.data_table_inference import infer_implied_legal_values
from aryx.cpq.logging_context import install_run_id_logging
from aryx.cpq.resolved_model_candidates import resolved_model_first_candidates
from aryx.cpq.state import MenuOption

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)


def inferred_first_available(
    vn: str, valid_opts: list[MenuOption], filled: dict[str, str],
    workspace_id: int | None, catalog_prefix: str,
    cache: dict[tuple[int, str], tuple] | None,
) -> MenuOption | None:
    """Lowest-order option of ``valid_opts`` inside the inferred legal set,
    or None (flag off / no workspace / no candidates / no evidence / no real
    option in the set). Never raises.

    With a known base model its own rows win; a base model that has rows for
    the attribute but no match (conflict) infers nothing, while a base model
    with no rows at all (sparse data) falls back to the model tier."""
    if workspace_id is None or not valid_opts:
        return None
    if not get_settings().cpq_infer_legal_values_enabled:
        return None
    from aryx.cpq.catalog_profile import resolve_base_model_vn

    try:
        base_model = filled.get(resolve_base_model_vn(filled, workspace_id, catalog_prefix, cache), "")
        product = filled.get("productSelectionProduct_all", "")
        for cpq_model in resolved_model_first_candidates(
            product, workspace_id, catalog_prefix, cache, base_model=base_model,
        ):
            inferred = infer_implied_legal_values(
                vn, cpq_model, workspace_id, catalog_prefix, cache, base_model=base_model,
                filled=filled,
            )
            if inferred is None:
                continue
            values, tier = inferred
            legal = sorted((o for o in valid_opts if o.item_value in values), key=lambda o: o.order)
            if not legal:
                continue
            logger.info(
                "cpq: inferred_legal_values vn=%r cpq_model=%r tier=%r values=%r picked=%r",
                vn, cpq_model, tier, values, legal[0].item_value,
            )
            return legal[0]
    except Exception:  # noqa: BLE001 -- inference must never break the fill pass
        logger.exception("cpq: inferred legal pick failed vn=%r", vn)
    return None
