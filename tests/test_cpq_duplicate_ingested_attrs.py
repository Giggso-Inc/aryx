"""Regression coverage for duplicate-ingested attrs (docs/
CPQ_SESSION_2_OPEN_ISSUES.md item 8).

Root cause (confirmed live, workspace 19): the entire SL3500e catalog was
accidentally ingested TWICE — every entity type doubled, timestamps exactly
one day apart (confirmed: ultimateDestinationCountry's two graph entities,
188302 and 212455, both carry the same real BM attribute id 39426962).
load_product_config's ConfigAttr construction had no dedup by variable_name,
so every duplicated attr became two independent ConfigAttr objects — both
landing in `pending_variables` whenever unfilled, surfacing as the SAME
question asked twice in one turn.
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


def test_duplicate_ingested_attr_collapses_to_one_config_attr(monkeypatch):
    # Same real BM attribute (source id 39426962), ingested twice under two
    # different graph entity ids — the exact confirmed live shape.
    entity_attrs = {
        188302: {"id": "39426962", "variable_name": "ultimateDestinationCountry",
                 "name": "Ultimate Destination Country", "required": "0",
                 "default_value": "", "order_number": "5"},
        212455: {"id": "39426962", "variable_name": "ultimateDestinationCountry",
                 "name": "Ultimate Destination Country", "required": "0",
                 "default_value": "", "order_number": "5"},
    }
    rdb = _FakeRdb(entity_attrs)
    import aryx.cpq.engine as engine_mod
    monkeypatch.setattr(engine_mod, "get_cpq_rdb", lambda: rdb)

    reader = _FakeReader(
        attr_type="Sl3500EConfigBmConfigAttr",
        entities=[
            {"id": 188302, "type": "Sl3500EConfigBmConfigAttr"},
            {"id": 212455, "type": "Sl3500EConfigBmConfigAttr"},
        ],
    )
    engine = CpqEngine()
    attrs, _ = engine.load_product_config(reader, workspace_id=19, product_hint="SL3500e")

    matches = [a for a in attrs if a.variable_name == "ultimateDestinationCountry"]
    assert len(matches) == 1, (
        "a variable_name ingested under 2 graph entities must collapse to "
        "ONE ConfigAttr, not surface as a duplicate pending question"
    )
    assert matches[0].entity_id == 212455, (
        "the higher (later-ingested) entity_id must win, not an arbitrary one"
    )


def test_catalog_wide_duplicate_ingestion_collapses_every_attr(monkeypatch):
    # Confirmed live: not an isolated attr — the WHOLE catalog was doubled
    # (277 distinct variable_names, 554 total rows, exactly 2x every one).
    # Model a small slice of that same shape: 3 distinct attrs, each with 2
    # entities.
    entity_attrs = {}
    entities = []
    for vn_i, vn in enumerate(["attrOne", "attrTwo", "attrThree"]):
        for copy in range(2):
            eid = 1000 + vn_i * 10 + copy
            entity_attrs[eid] = {
                "id": str(50000 + vn_i), "variable_name": vn, "name": vn,
                "required": "0", "default_value": "", "order_number": str(vn_i),
            }
            entities.append({"id": eid, "type": "Sl3500EConfigBmConfigAttr"})

    rdb = _FakeRdb(entity_attrs)
    import aryx.cpq.engine as engine_mod
    monkeypatch.setattr(engine_mod, "get_cpq_rdb", lambda: rdb)

    reader = _FakeReader(attr_type="Sl3500EConfigBmConfigAttr", entities=entities)
    engine = CpqEngine()
    attrs, _ = engine.load_product_config(reader, workspace_id=19, product_hint="SL3500e")

    assert len(attrs) == 3, "6 duplicated graph entities must collapse to 3 real attrs"
    assert {a.variable_name for a in attrs} == {"attrOne", "attrTwo", "attrThree"}


def test_non_duplicated_attrs_are_unaffected(monkeypatch):
    entity_attrs = {
        1: {"id": "1", "variable_name": "singleAttr", "name": "Single",
            "required": "0", "default_value": "", "order_number": "1"},
    }
    rdb = _FakeRdb(entity_attrs)
    import aryx.cpq.engine as engine_mod
    monkeypatch.setattr(engine_mod, "get_cpq_rdb", lambda: rdb)

    reader = _FakeReader(
        attr_type="SvxBmConfigAttr", entities=[{"id": 1, "type": "SvxBmConfigAttr"}],
    )
    engine = CpqEngine()
    attrs, _ = engine.load_product_config(reader, workspace_id=1, product_hint="SVX")

    assert len(attrs) == 1
    assert attrs[0].variable_name == "singleAttr"
