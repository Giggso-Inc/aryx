"""Product-level scope for the completeness check (flag `cpq_completeness_scope_by_product_enabled`).

ws 1267: APX 8000 and 6000 stop on the very first message with "missing required data: Is FLASHcode Available?, Quantity,
Power Adapter"; APX 4500/1500/6500 Enhanced stop after the first answers. A catalog marks those fields required for the whole
catalog, but they belong to other flows (flash upgrade, ASTRO systems): no attrSequence row of any of these models lists them.
`cpq_model_scoped_questions_enabled` removes such attributes only once the base model is known, which on the first message it is
not. Here an attribute that no base model of the product's models lists is left out of the check while the base model is empty."""
from __future__ import annotations

import logging
from typing import Any

from aryx.config import get_settings
from aryx.cpq.catalog_profile import PRODUCT_LITERAL, resolve_base_model_vn
from aryx.cpq.data_table.data_table_loader import _load_all_tables
from aryx.cpq.data_table_bridge.attr_governance import _is_unlisted_model_attr
from aryx.cpq.model_scoping_flags import scoped_anchor_vns

logger = logging.getLogger(__name__)


def product_scoped_attrs(engine: Any, attrs: list, session: Any, workspace_id: int | None, catalog_prefix: str) -> list:
    """`attrs` without the ones no base model of the product's models lists, while the base model is empty. Unchanged when
    the flag is off, the base model is known (the base-model scoping decides), the product has no sequence rows, or on any
    failure. Anchors and attributes holding a customer/engine-context value are kept."""
    if workspace_id is None or getattr(get_settings(), "cpq_completeness_scope_by_product_enabled", False) is not True:
        return attrs
    try:
        filled = session.filled or {}
        if filled.get(resolve_base_model_vn(filled, workspace_id, catalog_prefix, None), ""):
            return attrs
        product = filled.get(PRODUCT_LITERAL, "") or getattr(session, "product_name", "") or ""
        if not product:
            return attrs
        candidates = list(engine._cpq_model_candidates(product, workspace_id, catalog_prefix, None))
        _, sequence_rows, *_ = _load_all_tables(workspace_id, catalog_prefix, None)
        covered = {c for c in candidates if any(r.get("CPQModel") == c for r in sequence_rows)}
        if not covered:
            return attrs
        listed = {str(r.get("AttrName") or "") for r in sequence_rows if r.get("CPQModel") in covered}
        anchors = scoped_anchor_vns()
        sources = getattr(session, "filled_source", None)
        return [a for a in attrs
                if a.variable_name in listed or a.variable_name in anchors
                or not _is_unlisted_model_attr(a, filled, sources)]
    except Exception:  # noqa: BLE001 -- the check must never break a turn
        logger.debug("cpq: product-scoped completeness attributes failed; using the full list", exc_info=True)
        return attrs
