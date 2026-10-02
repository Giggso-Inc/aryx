"""Port of dev-rv-msi #351/#365/#366: CpqEngine.resolve_product_hint's new
first pass over the Basemodeltoconfig displayModel names (graph prefixed,
graph bare, then the RDB), gated behind
``cpq_basemodel_display_name_resolution_enabled`` (default off).
"""
from __future__ import annotations

import pytest

from aryx.config import get_settings
from aryx.cpq import engine as engine_module
from aryx.cpq.engine import CpqEngine


@pytest.fixture(autouse=True)
def _flag_on_and_restore():
    s = get_settings()
    prev = s.cpq_basemodel_display_name_resolution_enabled
    s.cpq_basemodel_display_name_resolution_enabled = True
    yield
    s.cpq_basemodel_display_name_resolution_enabled = prev


class _FakeRdb:
    """fetch_entity_attributes -> entity id -> attrs; optional exact-type rows."""

    def __init__(self, attrs_by_id: dict[int, dict], exact_rows: list | None = None):
        self._attrs_by_id = attrs_by_id
        self._exact_rows = exact_rows or []
        self.exact_calls: list[tuple] = []

    def fetch_entity_attributes(self, entity_ids, workspace_id):
        return {eid: self._attrs_by_id[eid] for eid in entity_ids if eid in self._attrs_by_id}

    def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
        self.exact_calls.append((workspace_id, ontology_type))
        return list(self._exact_rows)


class _FakeReader:
    def __init__(self, type_names: list[str], entities_by_type: dict[str, list[dict]]):
        self._type_names = type_names
        self._entities_by_type = entities_by_type
        self.queried: list[str] = []

    def distinct_types(self):
        return self._type_names

    def find_entities(self, ontology_type: str, limit: int = 0):
        self.queried.append(ontology_type)
        return self._entities_by_type.get(ontology_type, [])


@pytest.fixture
def make_engine(monkeypatch):
    def _make(basemodel_rows_by_prefix: dict[str, list[str]], extra_types: dict[str, list[dict]] | None = None):
        type_names = []
        entities_by_type: dict[str, list[dict]] = dict(extra_types or {})
        attrs_by_id: dict[int, dict] = {}
        next_id = 1
        for prefix, display_models in basemodel_rows_by_prefix.items():
            type_names.append(f"{prefix}BmPrdFamily")
            rows = []
            for dm in display_models:
                rows.append({"id": next_id})
                attrs_by_id[next_id] = {"displayModel": dm}
                next_id += 1
            entities_by_type[f"{prefix}Basemodeltoconfig"] = rows
        reader = _FakeReader(type_names, entities_by_type)
        rdb = _FakeRdb(attrs_by_id)
        monkeypatch.setattr(engine_module, "get_cpq_rdb", lambda: rdb)
        return CpqEngine(), reader

    return _make


# ---- ported from #351 (6 tests) -------------------------------------------

def test_unique_basemodel_match_resolves_directly(make_engine):
    engine, reader = make_engine({"Astro25Configdata": ["APX 900"]})
    assert engine.resolve_product_hint(reader, 110, "I want APX 900 for US") == (
        "Astro25Configdata", "APX 900")


def test_ambiguous_match_across_two_catalogs_returns_none_never_falls_through(make_engine):
    engine, reader = make_engine({
        "Astro25Configdata": ["APX 900"],
        "OtherCatalogData": ["APX 900"],
    })
    assert engine.resolve_product_hint(reader, 110, "I want APX 900 for US") is None


def test_longest_match_tiebreak_prefers_more_specific_model(make_engine):
    engine, reader = make_engine({"Astro25Configdata": ["APX 900", "APX 900 FLASHPORT"]})
    result = engine.resolve_product_hint(reader, 110, "I want the APX 900 FLASHPORT for US")
    assert result == ("Astro25Configdata", "APX 900 FLASHPORT")


def test_no_basemodel_match_falls_through_to_family_pass(make_engine):
    engine, reader = make_engine(
        {"Astro25Configdata": []},
        extra_types={"Astro25ConfigdataBmPrdFamily": [{"id": 500, "name": "aSTRO25"}]},
    )
    result = engine.resolve_product_hint(reader, 110, "I want an aSTRO25 radio for US")
    assert result == ("Astro25Configdata", "aSTRO25")


def test_short_hint_never_spuriously_matches_basemodel_row(make_engine):
    engine, reader = make_engine({"Astro25Configdata": ["APX 900"]})
    assert engine.resolve_product_hint(reader, 110, "US") is None


def test_no_prefixes_discovered_returns_none(make_engine):
    engine, reader = make_engine({})
    assert engine.resolve_product_hint(reader, 110, "I want APX 900 for US") is None


# ---- ported from #365 (unprefixed table) ----------------------------------

def test_unprefixed_basemodeltoconfig_table_still_resolves(monkeypatch):
    reader = _FakeReader(
        type_names=["Astro25ConfigdataBmPrdFamily"],
        entities_by_type={"Basemodeltoconfig": [{"id": 1}]},
    )
    monkeypatch.setattr(engine_module, "get_cpq_rdb", lambda: _FakeRdb({1: {"displayModel": "APX 3000"}}))
    result = CpqEngine().resolve_product_hint(reader, 110, "I want APX 3000 for US")
    assert result == ("Astro25Configdata", "APX 3000")


# ---- ported from #366 (RDB fallback) --------------------------------------

def test_basemodeltoconfig_never_graph_ingested_falls_back_to_rdb(monkeypatch):
    reader = _FakeReader(["Astro25ConfigdataBmPrdFamily"], {})
    rdb = _FakeRdb({}, exact_rows=[(1, {"displayModel": "APX 900"})])
    monkeypatch.setattr(engine_module, "get_cpq_rdb", lambda: rdb)
    result = CpqEngine().resolve_product_hint(reader, 110, "I want APX 900 for US")
    assert result == ("Astro25Configdata", "APX 900")
    assert rdb.exact_calls == [(110, "Basemodeltoconfig")]


def test_rdb_fallback_error_is_swallowed_and_falls_to_old_passes(monkeypatch):
    class _Boom(_FakeRdb):
        def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
            raise RuntimeError("db down")

    reader = _FakeReader(
        ["Astro25ConfigdataBmPrdFamily"],
        {"Astro25ConfigdataBmPrdFamily": [{"id": 500, "name": "aSTRO25"}]},
    )
    monkeypatch.setattr(engine_module, "get_cpq_rdb", lambda: _Boom({500: {"name": "aSTRO25"}}))
    result = CpqEngine().resolve_product_hint(reader, 110, "I want an aSTRO25 radio for US")
    assert result == ("Astro25Configdata", "aSTRO25")


def test_rdb_rows_fetched_once_per_resolve_call_not_once_per_prefix(monkeypatch):
    reader = _FakeReader(
        ["AlphaBmPrdFamily", "BetaBmPrdFamily", "GammaBmPrdFamily"], {})
    rdb = _FakeRdb({}, exact_rows=[(1, {"displayModel": "ZZZ NOMATCH"})])
    monkeypatch.setattr(engine_module, "get_cpq_rdb", lambda: rdb)
    assert CpqEngine().resolve_product_hint(reader, 110, "I want APX 900 for US") is None
    assert len(rdb.exact_calls) == 1


def test_rdb_match_with_multiple_prefixes_is_ambiguous_returns_none(monkeypatch):
    """The RDB fallback ignores the catalog prefix, so with 2+ catalogs the
    same match is reported for each and the 'matches in 2+ catalogs ->
    None, never fall through' contract applies (documented limitation)."""
    reader = _FakeReader(["AlphaBmPrdFamily", "BetaBmPrdFamily"], {})
    rdb = _FakeRdb({}, exact_rows=[(1, {"displayModel": "APX 900"})])
    monkeypatch.setattr(engine_module, "get_cpq_rdb", lambda: rdb)
    assert CpqEngine().resolve_product_hint(reader, 110, "I want APX 900 for US") is None


# ---- flag off is a no-op ---------------------------------------------------

def test_flag_off_skips_basemodel_pass_entirely(make_engine):
    get_settings().cpq_basemodel_display_name_resolution_enabled = False
    engine, reader = make_engine({"Astro25Configdata": ["APX 900"]})
    assert engine.resolve_product_hint(reader, 110, "I want APX 900 for US") is None
    assert not any("Basemodeltoconfig" in q for q in reader.queried)


def test_flag_off_does_not_touch_rdb(monkeypatch):
    get_settings().cpq_basemodel_display_name_resolution_enabled = False
    reader = _FakeReader(["Astro25ConfigdataBmPrdFamily"], {})
    rdb = _FakeRdb({}, exact_rows=[(1, {"displayModel": "APX 900"})])
    monkeypatch.setattr(engine_module, "get_cpq_rdb", lambda: rdb)
    assert CpqEngine().resolve_product_hint(reader, 110, "I want APX 900 for US") is None
    assert rdb.exact_calls == []


def test_flag_default_is_false():
    from aryx.config.config_cpq_intent import CpqIntentSettingsMixin

    field = CpqIntentSettingsMixin.model_fields["cpq_basemodel_display_name_resolution_enabled"]
    assert field.default is False
