"""Find the products that offer an attribute value in the ingested catalog.

Two sources, merged by model:

- Data Table: ground the phrase to attrToVarMapping labels (ground.py) and
  run search_products_by_feature() per (label, value spelling).
- Catalog menu options (menu_source.py): ground against each family's
  configuration-attribute labels and match the value against their menu
  options. This is where most real values live (e.g. carrier ATT/FIRSTNET).

With no value, every row/option for the label matches, which also yields
the list of values on offer. A rule-based index is a later phase.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from aryx.cpq.attribute_search.ground import ground_attribute_label, value_variants
from aryx.cpq.attribute_search.menu_source import search_menu_options
from aryx.cpq.attribute_search.seeds import trim_ambiguous_seeds
from aryx.cpq.data_table.data_table_product import (
    list_attribute_role_labels,
    search_products_by_feature,
)

logger = logging.getLogger(__name__)


@dataclass
class AttributeSearchResult:
    """What an attribute search found.

    `products` holds one dict per model: model, base_models, labels,
    attributes, values, sources (all sorted lists), plus `seeds` -- the
    values to fill in if a quote is started for it (catalog-menu hits only,
    ambiguous yes/no features dropped; see seeds.py). `offered_values` is every
    distinct value seen, mainly useful when no value was given.
    `feature_only` is True when every hit is a yes/no attribute -- the
    question was "which products have feature X", not "which value".
    """

    phrase: str
    labels: list[str]
    value: str | None
    products: list[dict[str, Any]] = field(default_factory=list)
    offered_values: list[str] = field(default_factory=list)
    feature_only: bool = False


def _group_by_model(hits: list[tuple[str, str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Merge (source, label, row) hits into one sorted entry per model."""
    grouped: dict[str, dict[str, set[str] | str]] = {}
    seeds: dict[str, list[dict[str, str]]] = {}
    for source, label, row in hits:
        model = str(row.get("model") or "").strip()
        if not model:
            continue
        entry = grouped.setdefault(model.upper(), {
            "model": model, "base_models": set(), "labels": set(),
            "attributes": set(), "values": set(), "sources": set(),
        })
        entry["labels"].add(label)
        entry["sources"].add(source)
        seed = _seed(row) if source == "catalog_menu" else None
        if seed is not None and seed not in seeds.setdefault(model.upper(), []):
            seeds[model.upper()].append(seed)
        for key, src in (("base_models", "base_model"), ("attributes", "attribute"),
                         ("values", "value")):
            if row.get(src):
                entry[key].add(str(row[src]))
    return [
        {**{k: (sorted(v) if isinstance(v, set) else v) for k, v in grouped[key].items()},
         "seeds": trim_ambiguous_seeds(seeds.get(key, []))}
        for key in sorted(grouped)
    ]


def _seed(row: dict[str, Any]) -> dict[str, str] | None:
    """The value to fill in for one catalog-menu hit, or None without a code."""
    if not row.get("item_value"):
        return None
    return {"vn": row["attribute"], "item_value": row["item_value"],
            "display": str(row.get("value") or ""), "select_type": row.get("select_type") or "",
            "kind": row.get("kind") or "option"}


def _data_table_hits(
    phrase: str, value: str | None, workspace_id: int, catalog_prefix: str,
) -> tuple[list[str], list[tuple[str, str, dict[str, Any]]]]:
    """Grounded attrToVarMapping labels and their (source, label, row) Data Table hits."""
    cache: dict[tuple, Any] = {}
    labels = ground_attribute_label(
        phrase, list_attribute_role_labels(workspace_id, catalog_prefix, cache=cache),
    )
    hits: list[tuple[str, str, dict[str, Any]]] = []
    for label in labels:
        for spelling in value_variants(value or "") or [""]:
            rows = search_products_by_feature(
                label, spelling, workspace_id, catalog_prefix=catalog_prefix, cache=cache,
            )
            hits.extend(("data_table", label, row) for row in rows)
    return labels, hits


def find_products_by_attribute(
    phrase: str, value: str | None, *, workspace_id: int, catalog_prefix: str = "",
    reader: Any = None, engine: Any = None,
) -> AttributeSearchResult | None:
    """Search the Data Table and catalog menus for products offering `value`.

    Args:
        phrase: Attribute as the user typed it, e.g. "carrier".
        value: Value as the user typed it, e.g. "ATT"; None for "any value".
        workspace_id: Workspace whose catalog to search.
        catalog_prefix: Optional catalog scope, passed through.
        reader: Graph reader; with `engine`, enables the menu-option source.
        engine: CpqEngine; without it only the Data Table is searched.

    Returns:
        None when `phrase` matches no real label in either source;
        otherwise the result, whose `products` may be empty.
    """
    labels, hits = _data_table_hits(phrase, value, workspace_id, catalog_prefix)
    menu_hits, menu_labels = search_menu_options(
        phrase, value, reader=reader, engine=engine, workspace_id=workspace_id,
    )
    hits.extend(("catalog_menu", row["label"], row) for row in menu_hits)
    # Each source grounded on its own vocabulary; keep only the best labels
    # across both, so a loose match in one never sits beside an exact one.
    labels = sorted(ground_attribute_label(phrase, sorted(set(labels) | set(menu_labels))))
    hits = [h for h in hits if h[1] in labels]
    if not labels:
        logger.info("attribute_search: phrase=%r grounded to no label ws=%s", phrase, workspace_id)
        return None
    products = _group_by_model(hits)
    offered = sorted({str(r.get("value")) for _, _, r in hits if r.get("value")})
    logger.info(
        "attribute_search: phrase=%r value=%r labels=%s products=%d ws=%s",
        phrase, value, labels, len(products), workspace_id,
    )
    feature_only = bool(hits) and all(r.get("kind") == "boolean" for _, _, r in hits)
    return AttributeSearchResult(
        phrase=phrase, labels=labels, value=(value or None),
        products=products, offered_values=offered, feature_only=feature_only,
    )
