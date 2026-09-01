"""docs/CPQ_CONFIG_ATTR_STATUS_FILTERING_ROOT_CAUSE_AND_FIX_PLAN_2026-08-14.md

Follow-up from the raven-review of PR #197 (fix/cpq-rule-status-filtering-
inactive-rules): the review's specific flagged gaps (BmFunction, Data
Table/whitelist, layout/array-set metadata) were all confirmed MOOT --
none of those entity types carry a `status` field in either real ingested
workspace. But a comprehensive real-data sweep found a DIFFERENT, live gap
the review didn't name: BmConfigAttr rows carry the exact same status=1
(active) / status=3 (inactive) convention as BmConfigRule, and
load_product_config's ConfigAttr construction never checked it -- 15 real
status=3 attribute rows exist in workspace 19 and were being loaded
unconditionally, same bug class as the original fix, one level down (the
attribute itself, not just the rules that target it).
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine


class _FakeRdb:
    def __init__(self, entity_attrs: dict[int, dict]):
        self._entity_attrs = entity_attrs

    def fetch_entity_attributes(self, entity_ids, workspace_id):
        return {eid: self._entity_attrs[eid] for eid in entity_ids if eid in self._entity_attrs}

    def fetch_attr_set_assoc(self, workspace_id, catalog_prefix=""):
        return {}


class _FakeReader:
    def __init__(self, attr_type: str, entities: list[dict]):
        self._attr_type = attr_type
        self._entities = entities

    def distinct_types(self):
        return [self._attr_type]

    def find_entities(self, ontology_type=None, name=None, limit=50, offset=0):
        if ontology_type != self._attr_type:
            return []
        return self._entities

    def neighbors(self, entity_id):
        return []


def _load(entity_attrs, entities, monkeypatch, attr_type="ApxNextConfigBmConfigAttr"):
    rdb = _FakeRdb(entity_attrs)
    import aryx.cpq.engine as engine_mod
    monkeypatch.setattr(engine_mod, "get_cpq_rdb", lambda: rdb)
    reader = _FakeReader(attr_type=attr_type, entities=entities)
    engine = CpqEngine()
    return engine.load_product_config(reader, workspace_id=19, product_hint="APX Next")


def test_inactive_status_3_attr_is_excluded(monkeypatch):
    entity_attrs = {
        100: {"id": "1001", "variable_name": "activeAttr_astro",
              "name": "Active Attr", "required": "0", "default_value": "",
              "order_number": "1", "status": "1"},
        101: {"id": "1002", "variable_name": "inactiveAttr_astro",
              "name": "Inactive Attr", "required": "0", "default_value": "",
              "order_number": "2", "status": "3"},
    }
    entities = [
        {"id": 100, "type": "ApxNextConfigBmConfigAttr"},
        {"id": 101, "type": "ApxNextConfigBmConfigAttr"},
    ]
    attrs, _ = _load(entity_attrs, entities, monkeypatch)
    names = {a.variable_name for a in attrs}
    assert "activeAttr_astro" in names
    assert "inactiveAttr_astro" not in names, (
        "a status=3 (inactive) BmConfigAttr must never be loaded into the "
        "ConfigAttr list -- it should not be shown/asked to the customer"
    )


def test_attr_with_no_status_field_is_unaffected():
    """Real data shows every BmConfigAttr row carries status, but the filter
    itself must not accidentally exclude an attr that happens to lack the
    field (defensive -- only an EXPLICIT '3' excludes, absence doesn't)."""
    import importlib
    import unittest.mock as mock
    entity_attrs = {
        200: {"id": "2001", "variable_name": "noStatusAttr_astro",
              "name": "No Status Attr", "required": "0", "default_value": "",
              "order_number": "1"},
    }
    entities = [{"id": 200, "type": "ApxNextConfigBmConfigAttr"}]
    rdb = _FakeRdb(entity_attrs)
    engine_mod = importlib.import_module("aryx.cpq.engine")
    with mock.patch.object(engine_mod, "get_cpq_rdb", return_value=rdb):
        reader = _FakeReader(attr_type="ApxNextConfigBmConfigAttr", entities=entities)
        attrs, _ = engine_mod.CpqEngine().load_product_config(
            reader, workspace_id=19, product_hint="APX Next")
    assert any(a.variable_name == "noStatusAttr_astro" for a in attrs)


def test_active_status_1_attr_is_loaded_normally(monkeypatch):
    entity_attrs = {
        300: {"id": "3001", "variable_name": "someAttr_astro", "name": "Some Attr",
              "required": "0", "default_value": "", "order_number": "1",
              "status": "1"},
    }
    entities = [{"id": 300, "type": "ApxNextConfigBmConfigAttr"}]
    attrs, _ = _load(entity_attrs, entities, monkeypatch)
    assert len(attrs) == 1
    assert attrs[0].variable_name == "someAttr_astro"
