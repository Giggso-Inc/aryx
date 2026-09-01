"""Coverage for CpqEngine.model_catalog_path (PR #230 review follow-up).

This method was unreachable until the sales-cpq confirm flow first
actually exercised it live — CpqEngine had no method of this name at all
(ported from cpq-streamlit's fork; see PR #225/#230), and
mcp_service.py's _product_route() calling it produced a bare
AttributeError. Locking in the happy path plus its two ValueError guards
so a future regression fails a test instead of a live confirm click.
"""
from __future__ import annotations

import pytest

from aryx.cpq.engine import CpqEngine


class _FakeTreeReader:
    """Same fixture shape as test_cpq_model_pointer.py's _FakeTreeReader."""

    def __init__(self, nodes, *, ontology_type="ApxNextConfigBmCatalog"):
        # nodes: list of (aryx_id, native_id, parent_id, name)
        self._nodes = nodes
        self._ontology_type = ontology_type

    def find_entities(self, ontology_type=None, name=None, limit=50, offset=0):
        if ontology_type != self._ontology_type:
            return []
        return [
            {"id": i, "type": ontology_type, "name": nm}
            for i, _nat, _par, nm in self._nodes
        ]


def _tree_engine(monkeypatch, nodes):
    engine = CpqEngine()
    fetched = {
        i: {"id": nat, "parent_id": par, "name": nm}
        for i, nat, par, nm in nodes
    }
    monkeypatch.setattr(
        engine, "_batch_fetch", lambda ids, ws: {i: fetched[i] for i in ids}
    )
    return engine


# family(root) -> line -> model(leaf), the 3-level shape resolve_catalog_path
# validates against a matching product_family name.
_TREE = [
    (1, "100", "-1", "aSTRO25_bom"),
    (2, "101", "100", "aSTRODevices_BOM"),
    (3, "102", "101", "aPXNext_BOM"),
]


def test_model_catalog_path_resolves_family_line_model(monkeypatch):
    engine = _tree_engine(monkeypatch, _TREE)

    result = engine.model_catalog_path(
        _FakeTreeReader(_TREE),
        1,
        "ApxNextConfig",
        "aPXNext_BOM",
        product_family="aSTRO25_bom",
    )

    assert result == {
        "product_family": "aSTRO25_bom",
        "product_line": "aSTRODevices_BOM",
        "model": "aPXNext_BOM",
    }


def test_model_catalog_path_falls_back_to_catalog_prefix_as_family(monkeypatch):
    """When the caller has no product_family, falls back to catalog_prefix
    rather than skipping validation silently (per the method's docstring)."""
    engine = _tree_engine(monkeypatch, _TREE)

    with pytest.raises(ValueError, match="does not belong to family"):
        engine.model_catalog_path(
            _FakeTreeReader(_TREE), 1, "ApxNextConfig", "aPXNext_BOM",
        )


def test_model_catalog_path_requires_catalog_prefix_and_model(monkeypatch):
    engine = _tree_engine(monkeypatch, _TREE)

    with pytest.raises(ValueError, match="required"):
        engine.model_catalog_path(
            _FakeTreeReader(_TREE), 1, "", "aPXNext_BOM",
            product_family="aSTRO25_bom",
        )

    with pytest.raises(ValueError, match="required"):
        engine.model_catalog_path(
            _FakeTreeReader(_TREE), 1, "ApxNextConfig", "",
            product_family="aSTRO25_bom",
        )


def test_model_catalog_path_raises_when_catalog_tree_not_found(monkeypatch):
    engine = _tree_engine(monkeypatch, _TREE)

    with pytest.raises(ValueError, match="was not found"):
        engine.model_catalog_path(
            _FakeTreeReader(_TREE, ontology_type="SomeOtherBmCatalog"),
            1,
            "ApxNextConfig",
            "aPXNext_BOM",
            product_family="aSTRO25_bom",
        )
