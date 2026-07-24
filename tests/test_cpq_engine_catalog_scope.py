"""Regression coverage for cross-catalog menu-item bleed in load_product_config.

Root cause (confirmed live, workspace 14): reader.neighbors() has no
catalog-prefix awareness. When an attribute's native id is reused across
catalogs from the same BM tenant (e.g. productSelectionProduct_all —
native id 39427019 in both APX Next and SVX), neighbors() returns
BmMenuItem entities from EVERY catalog sharing that native id, not just the
one resolved for the current request. See docs/CPQ_PRODUCT_SWITCH_TESTING_REPORT.md §7.
"""
from __future__ import annotations

import pytest

from aryx.cpq.engine import CpqEngine


class _FakeRdb:
    """Minimal get_cpq_rdb() double — only fetch_entity_attributes is used."""

    def __init__(self, entity_attrs: dict[int, dict]):
        self._entity_attrs = entity_attrs

    def fetch_entity_attributes(self, entity_ids, workspace_id):
        return {eid: self._entity_attrs[eid] for eid in entity_ids if eid in self._entity_attrs}

    def fetch_attr_set_assoc(self, workspace_id, catalog_prefix=""):
        return {}


class _FakeReader:
    """Graph-reader double with a single config attr whose menu-item
    neighbors span two catalog prefixes under the same shared native id —
    mirrors the confirmed live shape of productSelectionProduct_all.
    """

    def __init__(self, attr_type: str, neighbor_menu_items: list[dict]):
        self._attr_type = attr_type
        self._neighbor_menu_items = neighbor_menu_items

    def distinct_types(self):
        return [self._attr_type]

    def find_entities(self, ontology_type=None, name=None, limit=50, offset=0):
        if ontology_type != self._attr_type:
            return []
        return [{"id": 1, "type": self._attr_type, "name": "productSelectionProduct_all"}]

    def neighbors(self, entity_id):
        return self._neighbor_menu_items


@pytest.fixture()
def fake_rdb(monkeypatch):
    entity_attrs = {
        1: {"variable_name": "productSelectionProduct_all", "name": "Product",
            "required": "0", "default_value": "", "order_number": "10"},
        101: {"item_value": "VideoRSM-100", "item_text": "SVX Video RSM 100"},
        201: {"item_value": "APX-6500", "item_text": "APX 6500"},
    }
    rdb = _FakeRdb(entity_attrs)
    import aryx.cpq.engine as engine_mod
    monkeypatch.setattr(engine_mod, "get_cpq_rdb", lambda: rdb)
    return rdb


def test_menu_items_scoped_to_resolved_catalog_only(fake_rdb):
    """Only the resolved catalog's BmMenuItem neighbors should surface —
    a neighbor from a different catalog sharing the same native id must
    be filtered out, not merged in.
    """
    reader = _FakeReader(
        attr_type="SvxBmConfigAttr",
        neighbor_menu_items=[
            {"id": 101, "type": "SvxBmMenuItem"},   # same catalog — keep
            {"id": 201, "type": "ApxBmMenuItem"},   # different catalog — drop
        ],
    )
    engine = CpqEngine()
    attrs, _ = engine.load_product_config(reader, workspace_id=1, product_hint="SVX")

    assert len(attrs) == 1
    values = {o.item_value for o in attrs[0].options}
    assert values == {"VideoRSM-100"}
    assert "APX-6500" not in values


def test_menu_items_unfiltered_when_catalog_not_resolved(fake_rdb):
    """When attr_types only ever contain one prefix, resolved_catalog_prefix
    is that prefix (never ""), so this asserts the filter doesn't
    accidentally drop same-catalog neighbors — the common, single-catalog
    case must be unaffected.
    """
    reader = _FakeReader(
        attr_type="SvxBmConfigAttr",
        neighbor_menu_items=[{"id": 101, "type": "SvxBmMenuItem"}],
    )
    engine = CpqEngine()
    attrs, _ = engine.load_product_config(reader, workspace_id=1, product_hint="SVX")

    assert len(attrs) == 1
    assert [o.item_value for o in attrs[0].options] == ["VideoRSM-100"]
