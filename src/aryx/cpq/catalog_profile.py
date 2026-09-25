"""CatalogProfile shadow-mode role resolution.

Phase 3 (T1) pilot slice of CPQ_Hardcode_Audit_dev_oci_2026-09-25.md:
log-only comparison between today's hardcoded per-role variable-name
literals (e.g. `_BASE_MODEL_VN = "modelSelectionbaseModel_astro"`) and
what `resolve_variable_name_for_role()` -- the already-live, real
attrToVarMapping-Data-Table-driven resolver in `data_table_product.py`
-- would return for the session's actual CPQ model(s). Deliberately
does not change behaviour anywhere: every caller keeps using its
literal unconditionally, this only surfaces (via logging) whether the
literal and the real per-catalog mapping agree, ahead of any literal
ever being replaced by a resolved value.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.cpq.data_table.data_table_product import resolve_variable_name_for_role
from aryx.cpq.data_table_bridge.candidates import _cpq_model_candidates

logger = logging.getLogger(__name__)


def shadow_check_role_vn(
    role: str, literal_vn: str, product_name: str, workspace_id: int,
    catalog_prefix: str = "", cache: dict[tuple, Any] | None = None,
) -> None:
    """Best-effort, log-only: for each CPQ model `product_name` resolves
    to, compare `literal_vn` against what the real attrToVarMapping
    resolver gives for `role` under that model. Never raises -- a bug
    here must never affect the real cascade path this is called from.
    """
    try:
        models = _cpq_model_candidates(product_name, workspace_id, catalog_prefix, cache)
        for model in models:
            resolved = resolve_variable_name_for_role(
                model, role, workspace_id, catalog_prefix, cache,
            )
            if resolved is None or resolved == literal_vn:
                continue
            logger.warning(
                "CatalogProfile shadow mismatch: role=%r model=%r literal=%r "
                "resolved=%r (ws=%s catalog_prefix=%r)",
                role, model, literal_vn, resolved, workspace_id, catalog_prefix,
            )
    except Exception:
        logger.exception(
            "CatalogProfile shadow check failed for role=%r literal=%r "
            "(ws=%s) -- ignored, literal path unaffected",
            role, literal_vn, workspace_id,
        )
