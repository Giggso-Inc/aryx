"""Layout variants (CONFIG_DATA_AND_BEAUTIFY_CODE_FIX_PLAN_2026-10-05.md §3):
several layout exports per catalog keyed by the file's own `variableName`,
chosen per resolved model from the Configuration Flow rules. All names here
are synthetic; nothing in the code under test knows them.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aryx.cpq import engine as engine_module
from aryx.cpq import engine_caches
from aryx.cpq.engine import CpqEngine
from aryx.cpq.layout_and_join_data import layout_variant_context as ctx
from aryx.cpq.layout_and_join_data.layout_variant import layout_variant_for
from aryx.cpq.layout_source import DEFAULT_LAYOUT_VARIANT, layout_cache_key
from aryx.cpq_ingestion import layout_store

WS, PREFIX = 3, "CatX"
MODEL_ATTR_ID = 900
FLOW_A, FLOW_B = "flowAlpha", "flowBeta"


def _layout(var_name: str | None, names: list[str]) -> str:
    doc = {"status": "Active", "components": [
        {"resourceAttributeVarName": n, "hide": False, "resourceAttrType": "Text"} for n in names]}
    if var_name is not None:
        doc["variableName"] = var_name
    return json.dumps(doc)


class _Source:
    """In-memory LayoutFileSource with variant support."""

    def __init__(self, rows: dict[str, str]) -> None:
        self.rows = rows
        self.gets: list[str] = []

    def get(self, catalog_name, workspace_id, variant=DEFAULT_LAYOUT_VARIANT):
        self.gets.append(variant)
        return self.rows.get(variant)

    def variant_keys(self, catalog_name, workspace_id):
        return list(self.rows)


class _Rdb:
    """Two active flow rules (src ids 1, 2) whose inputs list model nodes."""

    def __init__(self, flow_inputs: dict[int, list[str]], rule_names: dict[int, str]) -> None:
        self.inputs, self.names = flow_inputs, rule_names

    def fetch_rules(self, ws, rule_type, prefix="", active_only=False, with_ref_id=False):
        assert rule_type == "6" and active_only
        return [(100 + sid, sid, f"rule{sid}", -1) for sid in self.names]

    def fetch_entity_attributes(self, eids, ws):
        return {e: {"variable_name": self.names[e - 100]} for e in eids}

    def fetch_entities_by_type(self, ws, suffix, prefix=""):
        return [(1, {"id": str(MODEL_ATTR_ID), "variable_name": ctx.MODEL_NODE_VAR}),
                (2, {"id": "901", "variable_name": "other"})]

    def fetch_rule_inputs(self, ws, prefix=""):
        rows = [(sid, MODEL_ATTR_ID, "~".join(vals), "4") for sid, vals in self.inputs.items()]
        rows.append((1, 901, "ignored", "4"))        # wrong attribute
        rows.append((1, MODEL_ATTR_ID, "skipme", "1"))  # wrong operator
        return rows


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    caches = (engine_caches._LAYOUT_COMPONENTS_CACHE, engine_caches._LAYOUT_DISPLAY_ORDER_CACHE,
              engine_caches._LAYOUT_FULL_ORDER_CACHE, engine_caches._LAYOUT_VARIANT_KEYS_CACHE,
              engine_caches._LAYOUT_FLOW_MAP_CACHE, engine_caches._LAYOUT_CONTROLSET_CACHE)
    for c in caches:
        c.clear()
    monkeypatch.setattr(engine_module, "get_cpq_rdb", lambda: _Rdb(
        {1: ["nodeA1", "NodeA2"], 2: ["nodeB1"]}, {1: FLOW_A, 2: FLOW_B}))
    ctx.bind_layout_model_node(None)
    yield
    ctx.bind_layout_model_node(None)
    for c in caches:
        c.clear()


def _flag(monkeypatch, on: bool) -> None:
    monkeypatch.setattr(ctx, "get_settings", lambda: SimpleNamespace(cpq_layout_variants_enabled=on))


def _two_variants() -> _Source:
    return _Source({FLOW_A: _layout(FLOW_A, ["a1", "a2"]), FLOW_B: _layout(FLOW_B, ["b1", "b2"])})


# ---- choosing the variant ---------------------------------------------------

def test_model_on_flow_a_picks_a_and_model_on_flow_b_picks_b():
    src = _two_variants()
    assert layout_variant_for(WS, PREFIX, "nodeA1", source=src) == FLOW_A
    assert layout_variant_for(WS, PREFIX, "NODEB1", source=src) == FLOW_B  # case-insensitive
    assert layout_variant_for(WS, PREFIX, "nodea2", source=src) == FLOW_A  # '~' list member


def test_flow_rule_beats_coverage():
    src = _two_variants()
    assert layout_variant_for(WS, PREFIX, "nodeB1", governed_names={"a1", "a2"}, source=src) == FLOW_B


def test_no_flow_rule_falls_back_to_best_coverage():
    src = _two_variants()
    assert layout_variant_for(WS, PREFIX, "unlisted", governed_names={"b1", "b2", "zz"}, source=src) == FLOW_B
    assert layout_variant_for(WS, PREFIX, "unlisted", governed_names=lambda: {"a1"}, source=src) == FLOW_A


def test_coverage_tie_goes_to_first_stored():
    src = _two_variants()
    assert layout_variant_for(WS, PREFIX, None, governed_names={"a1", "b1"}, source=src) == FLOW_A


def test_nothing_known_gives_sentinel_or_first_stored():
    assert layout_variant_for(WS, PREFIX, "unlisted", source=_two_variants()) == FLOW_A
    engine_caches._LAYOUT_VARIANT_KEYS_CACHE.clear()
    with_default = _Source({FLOW_B: _layout(FLOW_B, ["b1"]), DEFAULT_LAYOUT_VARIANT: _layout(None, ["d"])})
    assert layout_variant_for(WS, PREFIX, "unlisted", source=with_default) == DEFAULT_LAYOUT_VARIANT


def test_no_variant_stored_gives_sentinel():
    assert layout_variant_for(WS, PREFIX, "nodeA1", source=_Source({})) == DEFAULT_LAYOUT_VARIANT


# ---- the loaders ------------------------------------------------------------

def test_loader_picks_variant_from_bound_node_without_model_resolution(monkeypatch):
    _flag(monkeypatch, True)
    src, eng = _two_variants(), CpqEngine()
    ctx.bind_layout_model_node("nodeA1")
    assert eng.load_layout_display_order(WS, PREFIX, layout_source=src) == {"a1": 0, "a2": 1}
    ctx.bind_layout_model_node("nodeB1")
    assert eng.load_layout_display_order(WS, PREFIX, layout_source=src) == {"b1": 0, "b2": 1}
    assert eng._load_layout_full_order(WS, PREFIX, layout_source=src) == {"b1": 0, "b2": 1}
    assert engine_caches._LAYOUT_DISPLAY_ORDER_CACHE[layout_cache_key(WS, PREFIX, FLOW_A)]


def test_loader_uses_coverage_fallback_from_governed_names(monkeypatch):
    _flag(monkeypatch, True)
    monkeypatch.setattr(ctx, "current_governed_names", lambda ws, p: {"b2"})
    ctx.bind_layout_model_node("unlisted")
    assert CpqEngine().load_layout_display_order(WS, PREFIX, layout_source=_two_variants()) == {"b1": 0, "b2": 1}


def test_flag_off_ignores_variants(monkeypatch):
    _flag(monkeypatch, False)
    src = _two_variants()
    src.rows[DEFAULT_LAYOUT_VARIANT] = _layout(None, ["d1"])
    ctx.bind_layout_model_node("nodeB1")
    assert CpqEngine().load_layout_display_order(WS, PREFIX, layout_source=src) == {"d1": 0}
    assert set(src.gets) == {DEFAULT_LAYOUT_VARIANT}
    # flag off and only named variants stored: no layout, exactly as before
    only_named = _two_variants()
    engine_caches._LAYOUT_DISPLAY_ORDER_CACHE.clear()
    engine_caches._LAYOUT_COMPONENTS_CACHE.clear()
    assert CpqEngine().load_layout_display_order(WS, PREFIX, layout_source=only_named) is None


def test_flag_on_without_variants_keeps_single_layout(monkeypatch):
    _flag(monkeypatch, True)
    src = _Source({DEFAULT_LAYOUT_VARIANT: _layout(None, ["d1", "d2"])})
    ctx.bind_layout_model_node("nodeA1")
    assert CpqEngine().load_layout_display_order(WS, PREFIX, layout_source=src) == {"d1": 0, "d2": 1}
    assert (WS, PREFIX) in engine_caches._LAYOUT_DISPLAY_ORDER_CACHE  # historical key


def test_explicit_variant_argument_is_honoured(monkeypatch):
    _flag(monkeypatch, False)
    assert CpqEngine().load_layout_display_order(
        WS, PREFIX, layout_source=_two_variants(), variant=FLOW_B) == {"b1": 0, "b2": 1}


# ---- write side -------------------------------------------------------------

class _Pool:
    """Emulates the upsert: rows keyed by (workspace_id, catalog_prefix, variant)."""

    def __init__(self) -> None:
        self.rows: dict[tuple, dict] = {}

    def connection(self):
        pool = self

        class _Cur:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, sql, params):
                pool.rows[(params["workspace_id"], params["catalog_prefix"], params["variant"])] = params

        class _Conn:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def cursor(self): return _Cur()

        return _Conn()


class _Ds:
    def __init__(self, dsn): pass
    def ensure(self, *a): return {}


def _store_flag(monkeypatch, on):
    from unittest.mock import MagicMock
    m = MagicMock()
    m.return_value.cpq_layout_variants_enabled = on
    monkeypatch.setattr(layout_store, "get_settings", m)


@pytest.fixture
def pool(monkeypatch):
    p = _Pool()
    monkeypatch.setattr(layout_store, "get_pool", lambda dsn: p)
    monkeypatch.setattr(layout_store, "DatasourceStore", _Ds)
    _store_flag(monkeypatch, True)
    return p


def _store(text: str, name: str = "f.json") -> None:
    layout_store.store_layout_file(text.encode(), name, workspace_id=WS, dsn="d", catalog_prefix=PREFIX)


def test_variant_derived_from_variable_name_and_reupload_replaces_only_it(pool):
    _store(_layout(FLOW_A, ["a1"]), "one.json")
    _store(_layout(FLOW_B, ["b1"]), "two.json")
    assert {k[2] for k in pool.rows} == {FLOW_A, FLOW_B}
    _store(_layout(FLOW_A, ["a1", "a9"]), "three.json")
    assert len(pool.rows) == 2
    assert pool.rows[(WS, PREFIX, FLOW_A)]["filename"] == "three.json"
    assert pool.rows[(WS, PREFIX, FLOW_B)]["filename"] == "two.json"


def test_flag_off_a_reupload_always_replaces_the_default_row(pool, monkeypatch):
    _store_flag(monkeypatch, False)
    _store(_layout(FLOW_A, ["a1"]), "one.json")
    _store(_layout(FLOW_B, ["b1"]), "two.json")
    assert list(pool.rows) == [(WS, PREFIX, DEFAULT_LAYOUT_VARIANT)]
    assert pool.rows[(WS, PREFIX, DEFAULT_LAYOUT_VARIANT)]["filename"] == "two.json"


@pytest.mark.parametrize("content", ["not json", "[1, 2]", '{"status": "Active"}',
                                     '{"variableName": ""}', '{"variableName": 5}'])
def test_missing_or_invalid_variable_name_gets_sentinel(pool, content):
    _store(content)
    assert {k[2] for k in pool.rows} == {DEFAULT_LAYOUT_VARIANT}


def test_invalidate_clears_every_variant_of_the_prefix(pool):
    other = (WS + 1, PREFIX)
    for cache in (engine_caches._LAYOUT_COMPONENTS_CACHE, engine_caches._LAYOUT_DISPLAY_ORDER_CACHE):
        for variant in (DEFAULT_LAYOUT_VARIANT, FLOW_A, FLOW_B):
            cache[layout_cache_key(WS, PREFIX, variant)] = {"stale": 1}
        cache[other] = {"keep": 1}
    engine_caches._LAYOUT_VARIANT_KEYS_CACHE[(WS, PREFIX)] = [FLOW_A]
    engine_caches._LAYOUT_FLOW_MAP_CACHE[(WS, PREFIX)] = {}
    _store(_layout(FLOW_A, ["a1"]))
    assert list(engine_caches._LAYOUT_COMPONENTS_CACHE) == [other]
    assert list(engine_caches._LAYOUT_DISPLAY_ORDER_CACHE) == [other]
    assert not engine_caches._LAYOUT_VARIANT_KEYS_CACHE and not engine_caches._LAYOUT_FLOW_MAP_CACHE


# ---- SQL / migrations -------------------------------------------------------

_SRC = Path(__file__).resolve().parents[1] / "src" / "aryx"


def test_sql_files_key_on_variant_for_both_dialects():
    for rel in ("queries/upsert_cpq_layout_file.sql", "queries/oracle/upsert_cpq_layout_file.sql"):
        assert "variant" in (_SRC / rel).read_text(encoding="utf-8")
    assert "variant = %s" in (_SRC / "queries/select_cpq_layout_file.sql").read_text(encoding="utf-8")
    pg = (_SRC / "queries/upsert_cpq_layout_file.sql").read_text(encoding="utf-8")
    assert "ON CONFLICT (workspace_id, catalog_prefix, variant)" in pg
    for rel in ("store/migrations/0050_cpq_layout_variant.sql",
                "store/migrations_oracle/0050_cpq_layout_variant.sql"):
        text = (_SRC / rel).read_text(encoding="utf-8")
        assert f"'{DEFAULT_LAYOUT_VARIANT}'" in text or f"''{DEFAULT_LAYOUT_VARIANT}''" in text
        assert "workspace_id, catalog_prefix, variant" in text
