"""Port of aryxent PR1/PR2/PR3 (per-turn model resolution, context seeding,
model-scoped lookups) into dev_oci. All flags default off and must leave
behaviour unchanged when off.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aryx.api.ask_model_leaf import ask_model_leaf_bind as bind
from aryx.cpq import model_resolution as mr
from aryx.cpq import model_resolution_catalog as mrc
from aryx.cpq import model_scope_pick as msp
from aryx.cpq.data_table_bridge import candidates as cand
from aryx.cpq.state import MenuOption


def _cfg(**kw):
    m = MagicMock()
    for k, v in kw.items():
        setattr(m.return_value, k, v)
    return m


class FakeRdb:
    """Stands in for CpqRdb.fetch_entities_by_exact_type (Postgres/Oracle)."""

    def __init__(self, rows: dict[str, list[dict]]):
        self.rows = rows

    def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
        return [(i, r) for i, r in enumerate(self.rows.get(ontology_type, []))]


def _rdb() -> FakeRdb:
    return FakeRdb({
        "XBmCatalog": [
            {"id": "1", "name": "astro", "parent_id": "-1"},
            {"id": "2", "name": "aPX900", "parent_id": "1"},
            {"id": "3", "name": "aPX9000", "parent_id": "1"},
            {"id": "4", "name": "aPX900Old", "parent_id": "1"},
        ],
        "Basemodeltoconfig": [
            {"cpqModel": "APX900", "displayModel": "APX 900", "CPQModelVariableName": "aPX900", "baseModel": "T1"},
            {"cpqModel": "APX900", "displayModel": "APX 900", "CPQModelVariableName": "aPX900", "baseModel": "T2"},
            {"cpqModel": "APX9000", "displayModel": "APX 9000", "CPQModelVariableName": "aPX9000", "baseModel": "T3"},
            {"cpqModel": "APX900-remove", "displayModel": "APX 900", "baseModel": "T9"},
        ],
        "Flagsforflashport": [],
        "XBmConfigRule": [],
    })


@pytest.fixture(autouse=True)
def _clean():
    mrc._cache.clear()
    mrc._empty.clear()
    mr.bind_turn(None)
    yield
    mrc._cache.clear()
    mrc._empty.clear()
    mr.bind_turn(None)


def _resolve(text: str) -> mr.ModelResolution:
    return mr.resolve_model(text, 1, "X", _rdb())


# ---- PR1: resolver ----
def test_exact_name_resolves_and_no_digit_bleed():
    res = _resolve("I want APX 900 for US")
    assert res.resolved and res.chosen.cpq_model == "APX900"
    assert res.chosen.node_name == "aPX900"
    assert res.scope_node_ids == frozenset({"2", "1"})
    # "apx900" must not match inside "apx9000"
    assert _resolve("quote an APX 9000").chosen.cpq_model == "APX9000"


def test_soft_deleted_variant_dropped_and_ambiguous_picks_top():
    res = _resolve("APX 900")
    assert res.chosen.cpq_model == "APX900"
    assert [a.cpq_model for a in res.alternatives] == ["APX900-remove"]
    assert res.deciding_step == "drop_soft_deleted"


def test_unresolved_and_rank_empty():
    assert not _resolve("a radio please").resolved
    assert mr.rank_candidates([]) == (None, (), "no_match")


def test_ranking_prefers_longest_then_alphabetical():
    def c(name, ln, kind="exact"):
        return mr.ModelCandidate(name, frozenset(), None, None, frozenset(), kind, False, False, ln)
    top, alts, step = mr.rank_candidates([c("B", 7), c("A", 15, "partial")])
    assert top.cpq_model == "A" and step == "longest_name_match" and len(alts) == 1
    top, _a, step = mr.rank_candidates([c("B", 7), c("A", 7)])
    assert top.cpq_model == "A" and step == "alphabetical"


def test_turn_binding_roundtrip():
    assert mr.get_turn() is None
    ctx = mr.TurnModelContext(_resolve("APX 900"), 1, "X")
    mr.bind_turn(ctx)
    assert mr.get_turn() is ctx
    assert ctx.first_time(("k",)) and not ctx.first_time(("k",))
    assert "APX900" in mr.describe(ctx.resolution)


# ---- turn binding in the ask flow ----
def _req():
    return SimpleNamespace(question="I want APX 900", workspace_id=1)


def test_bind_flag_off_binds_nothing():
    with patch.object(bind, "get_settings", _cfg(cpq_model_resolution_enabled=False)):
        bind.bind_turn_model_context(_req(), SimpleNamespace(product_anchor_question=""), "X", None)
    assert mr.get_turn() is None


def test_bind_flag_on_binds_resolution():
    with patch.object(bind, "get_settings", _cfg(cpq_model_resolution_enabled=True)), \
         patch.object(mr, "load_catalog", lambda w, p, rdb=None: mrc.load_catalog(w, p, _rdb())):
        bind.bind_turn_model_context(_req(), SimpleNamespace(product_anchor_question=""), "X", None)
    assert mr.get_turn().resolution.chosen.cpq_model == "APX900"


# ---- PR2: seeding ----
def _bound():
    mr.bind_turn(mr.TurnModelContext(_resolve("APX 900"), 1, "X"))


def test_seed_off_returns_empty_even_when_bound():
    _bound()
    with patch.object(bind, "get_settings", _cfg(cpq_model_context_seed_enabled=False)):
        assert bind.seed_model_vn_from_resolution() == ""


def test_seed_on_returns_node_name_and_empty_when_unbound():
    with patch.object(bind, "get_settings", _cfg(cpq_model_context_seed_enabled=True)):
        assert bind.seed_model_vn_from_resolution() == ""
        _bound()
        assert bind.seed_model_vn_from_resolution() == "aPX900"


def test_pick_top_text_match():
    _bound()
    with patch.object(bind, "get_settings", _cfg(cpq_model_leaf_pick_top_enabled=False)):
        assert bind.pick_top_text_match(["aPX900", "aPX900Old"]) is None
    with patch.object(bind, "get_settings", _cfg(cpq_model_leaf_pick_top_enabled=True)):
        assert bind.pick_top_text_match(["aPX900Old", "aPX900"]) == "aPX900"
        assert bind.pick_top_text_match(["aPX900"]) is None


# ---- PR3a: candidate prepend ----
def test_prepend_off_is_noop():
    _bound()
    with patch.object(cand, "get_settings", _cfg(cpq_model_scope_lookups_enabled=False)):
        assert cand._prepend_resolved_model(("FOO",), "p", "") == ("FOO",)


def test_prepend_on_adds_when_missing_only():
    with patch.object(cand, "get_settings", _cfg(cpq_model_scope_lookups_enabled=True)):
        assert cand._prepend_resolved_model(("FOO",), "p", "") == ("FOO",)  # unbound
        _bound()
        assert cand._prepend_resolved_model(("FOO",), "p", "") == ("APX900", "FOO")
        assert cand._prepend_resolved_model(("FOO", "APX900"), "p", "") == ("FOO", "APX900")


# ---- PR3b: scoped first-available ----
OPTS = [MenuOption(item_value=v, display_name=v) for v in ("STANDARD", "WHIP")]


def test_scoped_pick_flag_off_none():
    _bound()
    with patch.object(msp, "get_settings", _cfg(cpq_model_scope_lookups_enabled=False)), \
         patch.object(msp, "dt_resolve_whitelist_values", MagicMock(return_value=["WHIP"])) as wl:
        assert msp.scoped_first_available("v", OPTS, {}, 1, "X", None) is None
        wl.assert_not_called()


def test_scoped_pick_flag_on_takes_first_legal():
    wl = MagicMock(return_value=["WHIP"])
    with patch.object(msp, "get_settings", _cfg(cpq_model_scope_lookups_enabled=True)), \
         patch.object(msp, "dt_resolve_whitelist_values", wl):
        assert msp.scoped_first_available("v", OPTS, {}, 1, "X", None) is None  # unbound
        _bound()
        got = msp.scoped_first_available("v", OPTS, {"modelSelectionbaseModel_astro": "T1"}, 1, "X", None)
        assert got.item_value == "WHIP"
        assert wl.call_args.args[:3] == ("APX900", "T1", "v")
        # base model not one of the model's own -> ALL rows only
        msp.scoped_first_available("v", OPTS, {"modelSelectionbaseModel_astro": "ZZ"}, 1, "X", None)
        assert wl.call_args.args[1] == ""


def test_scoped_pick_none_when_no_legal_or_error():
    _bound()
    with patch.object(msp, "get_settings", _cfg(cpq_model_scope_lookups_enabled=True)):
        with patch.object(msp, "dt_resolve_whitelist_values", MagicMock(return_value=None)):
            assert msp.scoped_first_available("v", OPTS, {}, 1, "X", None) is None
        with patch.object(msp, "dt_resolve_whitelist_values", MagicMock(return_value=[])):
            assert msp.scoped_first_available("v", OPTS, {}, 1, "X", None) is None
        with patch.object(msp, "dt_resolve_whitelist_values", MagicMock(side_effect=RuntimeError)):
            assert msp.scoped_first_available("v", OPTS, {}, 1, "X", None) is None
