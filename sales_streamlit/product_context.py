"""Resolve sales MSI product routes from Aryx BmCatalog nodes."""

from __future__ import annotations

from typing import Any, Iterable

CatalogNode = dict[str, str]


def _text(node: dict[str, Any], key: str, fallback: str = "") -> str:
    """Return one normalized catalog node field."""
    return str(node.get(key) or fallback).strip()


def _index_nodes(
    nodes: Iterable[dict[str, Any]],
) -> tuple[list[CatalogNode], dict[str, CatalogNode], dict[str, list[CatalogNode]]]:
    """Normalize catalog nodes and build identifier and name indexes."""
    normalized = [
        {
            "native_id": _text(node, "native_id", _text(node, "id")),
            "parent_id": _text(node, "parent_id"),
            "name": _text(node, "name"),
        }
        for node in nodes
    ]
    by_id: dict[str, CatalogNode] = {}
    named: dict[str, list[CatalogNode]] = {}
    for node in normalized:
        native_id = node["native_id"]
        if native_id in by_id:
            raise ValueError(f"BmCatalog native id {native_id!r} is duplicated")
        if native_id:
            by_id[native_id] = node
        if node["name"]:
            named.setdefault(node["name"], []).append(node)
    return normalized, by_id, named


def _select_leaf(
    normalized: list[CatalogNode],
    named: dict[str, list[CatalogNode]],
    model: str,
) -> CatalogNode:
    """Return the uniquely named leaf node for a model."""
    matches = named.get(model) or []
    if not matches:
        raise ValueError(f"Model {model!r} was not found in the BmCatalog tree")
    if len(matches) != 1:
        raise ValueError(f"Model {model!r} is ambiguous in the BmCatalog tree")
    selected = matches[0]
    parent_ids = {
        node["parent_id"]
        for node in normalized
        if node["parent_id"] and node["parent_id"] != "-1"
    }
    if selected["native_id"] in parent_ids:
        raise ValueError(f"Model {model!r} is not a BmCatalog leaf")
    return selected


def _root_node(selected: CatalogNode, by_id: dict[str, CatalogNode]) -> CatalogNode:
    """Walk a catalog branch and return its validated root node."""
    cursor = selected
    seen: set[str] = set()
    root = selected
    while cursor["parent_id"] and cursor["parent_id"] != "-1":
        if cursor["native_id"] in seen:
            raise ValueError("BmCatalog tree contains an ancestor cycle")
        seen.add(cursor["native_id"])
        ancestor = by_id.get(cursor["parent_id"])
        if ancestor is None:
            raise ValueError("BmCatalog tree contains a missing ancestor")
        root = ancestor
        cursor = ancestor
    return root


def resolve_catalog_path(
    nodes: Iterable[dict[str, Any]],
    *,
    product_family: str,
    model: str,
) -> dict[str, str]:
    """Return ProductFamily/ProductLine/Model after validating a leaf path.

    ``native_id`` and ``parent_id`` are catalog-native identifiers. The
    selected model must be a leaf, and its direct parent is the product
    line. Some BmCatalog trees encode the family itself as the top node
    (root's parent_id == "-1"; a 3-level family->line->model tree) — for
    those, walking ancestors must reach a root whose name matches the
    requested family, same integrity check as always. Others (confirmed
    live: APX Next's own tree) only ever encode line->model, with the
    family living in a separate BmPrdFamily entity outside this tree
    entirely — there, the walked "root" IS the line node itself, so it
    can never equal the family name by construction; skip the equality
    check in that case rather than rejecting every valid model in every
    2-level catalog.
    """
    normalized, by_id, named = _index_nodes(nodes)
    selected = _select_leaf(normalized, named, model)
    parent = by_id.get(selected["parent_id"])
    if parent is None:
        raise ValueError(f"Model {model!r} has no product-line parent")
    root = _root_node(selected, by_id)
    if root["native_id"] != parent["native_id"] and root["name"] != product_family:
        raise ValueError(
            f"Model {model!r} does not belong to family {product_family!r}"
        )
    return {
        "product_family": product_family,
        "product_line": parent["name"],
        "model": model,
    }
