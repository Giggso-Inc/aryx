"""Validated family/line/model path for MSI (Phase 4 step 11 extraction
from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`model_catalog_path` walks the same BmCatalog tree `model_leaves` does,
but hands the flattened nodes to sales_streamlit's `resolve_catalog_path`
for family-membership validation. The `resolve_catalog_path` import
stays function-local exactly as it was in engine.py -- importing
sales_streamlit at module scope would make this package depend on the
UI layer at import time.

`_batch_fetch` goes back through the passed-in `engine` instance.
"""

from __future__ import annotations

from typing import Any


def model_catalog_path(
    engine: Any,
    reader: Any,
    workspace_id: int,
    catalog_prefix: str,
    model: str,
    product_family: str = "",
) -> dict[str, str]:
    """Return the validated family, line, and leaf model for MSI.

    The route uses the same BmCatalog tree as
    :meth:`single_model_variable_name` and
    :meth:`model_variable_candidates`; it never derives identity from a
    generic Product attribute.

    ``catalog_prefix`` (e.g. "ApxNextConfig") is the ontology-type
    namespace used to find this catalog's entities in the graph — it is
    NOT the catalog's own root node name (e.g. "aSTRO25_bom"), which is
    what resolve_catalog_path's family-membership check validates
    against. Conflating the two here previously made the family check
    impossible to pass (catalog_prefix never equals a root node's
    name) — this was unreachable until the sales-cpq confirm flow
    first actually exercised it live. When the caller doesn't have the
    product_family name available, falls back to catalog_prefix (the
    old, always-failing behavior) rather than skipping validation
    silently.
    """
    from sales_streamlit.product_context import resolve_catalog_path

    if not catalog_prefix or not model:
        raise ValueError("Product family and resolved model are required")
    entities = reader.find_entities(
        ontology_type=f"{catalog_prefix}BmCatalog",
        limit=200,
    )
    if not entities:
        raise ValueError(
            f"BmCatalog tree for family {catalog_prefix!r} was not found"
        )
    properties = engine._batch_fetch(
        [entity["id"] for entity in entities],
        workspace_id,
    )
    nodes = []
    for entity in entities:
        attrs = properties.get(entity["id"], {})
        nodes.append(
            {
                "native_id": str(attrs.get("id") or "").strip(),
                "parent_id": str(attrs.get("parent_id") or "").strip(),
                "name": str(
                    attrs.get("name") or entity.get("name") or ""
                ).strip(),
            }
        )
    return resolve_catalog_path(
        nodes,
        product_family=product_family or catalog_prefix,
        model=model,
    )
