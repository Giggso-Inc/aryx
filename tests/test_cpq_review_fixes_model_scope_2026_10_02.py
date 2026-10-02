"""PR 412 review fixes for the model-scope ports (rule scope, catalog cache,
seed validation, pick-top gating, candidate ordering, ranking rule).
Run with PYTHONPATH=src.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aryx.api.ask_model_leaf import ask_model_leaf_bind as bind
from aryx.api.ask_model_leaf import ask_model_leaf_resolve as leaf_resolve
from aryx.cpq import model_resolution as mr
from aryx.cpq import model_resolution_catalog as mrc
from aryx.cpq import rule_scope
from aryx.cpq.data_table_bridge import candidates as cand
from aryx.cpq.state import HidingRule


def _cfg(**kw):
    m = MagicMock()
    for k, v in kw.items():
        setattr(m.return_value, k, v)
    return m


class FakeRdb:
    def __init__(self, rows):
        self.rows = rows

    def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
        return [(i, r) for i, r in enumerate(self.rows.get(ontology_type, []))]


def _rdb():
    return FakeRdb({
        "XBmCatalog": [
            {"id": "1", "name": "astro", "parent_id": "-1"},
            {"id": "2", "name": "aPX6000", "parent_id": "1"},
            {"id": "3", "name": "aPX8000", "parent_id": "1"},
            {"id": "4", "name": "aPX7000", "parent_id": "1"},
        ],
        "Basemodeltoconfig": [
            {"cpqModel": "APX6000", "displayModel": "APX 6000", "CPQModelVariableName": "aPX6000", "baseModel": "T1"},
            {"cpqModel": "APX8000", "displayModel": "APX 8000", "CPQModelVariableName": "aPX8000", "baseModel": "T2"},
            {"cpqModel": "APX7000", "displayModel": "APX 7000", "CPQModelVariableName": "aPX7000", "baseModel": "T3"},
            {"cpqModel": "APX7000X", "displayModel": "APX 7000", "CPQModelVariableName": "aPX7000", "baseModel": "T4"},
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


def _bind(scope, resolved=True, ws=1, prefix="X", load=True):
    if load:
        mrc.load_catalog(ws, prefix, _rdb())
    chosen = mr.ModelCandidate(
        cpq_model="APX6000", display_names=frozenset(), node_name="aPX6000", node_id="2",
        base_models=frozenset(), match="exact", is_upgrade=False, soft_deleted=False,
    ) if resolved else None
    res = mr.ModelResolution(
        chosen=chosen, alternatives=(), deciding_step="x",
        source="hint" if resolved else "unresolved", scope_node_ids=frozenset(scope),
    )
    mr.bind_turn(mr.TurnModelContext(resolution=res, workspace_id=ws, catalog_prefix=prefix))


def _rules(*refs):
    return [HidingRule(f"r{i}", 0, "", 1, ref_id=ref) for i, ref in enumerate(refs)]


# ---- rule scope: High 1 / High 2 ----
def test_empty_scope_keeps_all_rules():
    _bind(scope=())
    rules = _rules("2", "99", "3")
    with patch.object(rule_scope, "get_settings", _cfg(cpq_rule_scope_filter_enabled=True)):
        assert rule_scope.scope_rules_by_ancestry(rules, "x") is rules


def test_non_node_ref_id_and_minus_one_kept_node_outside_scope_dropped():
    _bind(scope=("2", "1"))
    rules = _rules("2", "family-level-uuid", "-1", "3", "")
    with patch.object(rule_scope, "get_settings", _cfg(cpq_rule_scope_filter_enabled=True)):
        kept = rule_scope.scope_rules_by_ancestry(rules, "x")
    assert [r.ref_id for r in kept] == ["2", "family-level-uuid", "-1", ""]  # "3" is a node outside scope


def test_minus_one_kept_even_without_cached_catalog():
    _bind(scope=("2",), load=False)
    rules = _rules("-1", "3")
    with patch.object(rule_scope, "get_settings", _cfg(cpq_rule_scope_filter_enabled=True)):
        kept = rule_scope.scope_rules_by_ancestry(rules, "x")
    assert [r.ref_id for r in kept] == ["-1"]


def test_workspace_or_prefix_mismatch_returns_unfiltered():
    _bind(scope=("2",), ws=1, prefix="X")
    rules = _rules("3")
    with patch.object(rule_scope, "get_settings", _cfg(cpq_rule_scope_filter_enabled=True)):
        assert rule_scope.scope_rules_by_ancestry(rules, "x", 2, "X") is rules
        assert rule_scope.scope_rules_by_ancestry(rules, "x", 1, "Y") is rules
        assert rule_scope.scope_rules_by_ancestry(rules, "x", 1, "X") == []


# ---- catalog cache: Medium 9 ----
def test_empty_catalog_not_cached_and_warns(caplog):
    empty = FakeRdb({})
    with caplog.at_level(logging.WARNING, logger=mrc.logger.name):
        data = mrc.load_catalog(5, "X", empty)
    assert not data.models and mrc.cached(5, "X") is None
    assert any("empty cache" in r.getMessage() for r in caplog.records)
    # an expired short negative cache lets a healthy DB load for real (no 10-minute poisoning)
    with patch.object(mrc, "_EMPTY_TTL_S", 0.0):
        assert mrc.load_catalog(5, "X", _rdb()).models
    assert mrc.cached(5, "X") is not None


def test_empty_catalog_short_negative_cache_avoids_rescan():
    class CountingRdb(FakeRdb):
        calls = 0

        def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
            CountingRdb.calls += 1
            return super().fetch_entities_by_exact_type(workspace_id, ontology_type)

    empty = CountingRdb({})
    mrc.load_catalog(6, "X", empty)
    first = CountingRdb.calls
    mrc.load_catalog(6, "X", empty)
    assert CountingRdb.calls == first          # second call served from the negative cache
    mrc.invalidate(6)
    mrc.load_catalog(6, "X", empty)
    assert CountingRdb.calls > first           # invalidate clears the negative cache too


def test_invalidate_drops_cache():
    mrc.load_catalog(1, "X", _rdb())
    mrc.invalidate(1)
    assert mrc.cached(1, "X") is None


# ---- seed validation: Medium 10 ----
def _session(pending=None):
    return SimpleNamespace(
        pending_model_leaf_candidates=list(pending or []), model_leaf_resolved=False,
        filled={}, product_anchor_question="", run_id="r",
    )


def _run_leaf(seed, session, pending_reply=None):
    engine = MagicMock()
    engine.single_model_variable_name.return_value = ""
    engine.model_variable_candidates.return_value = ["aPX6000", "aPX8000"]
    hints: dict = {"_bm_model_variable_name": "unvalidatedCamel"}
    asked = {"ask": True}
    api = SimpleNamespace(_cpq_engine=engine)
    req = SimpleNamespace(question="hello", workspace_id=1)
    with patch("aryx.api.ask_api._cpq_engine", engine), \
            patch.object(leaf_resolve, "bind_turn_model_context"), \
            patch.object(leaf_resolve, "seed_model_vn_from_resolution", return_value=seed), \
            patch.object(leaf_resolve, "_build_model_leaf_ask_prompt", return_value=asked), \
            patch.object(leaf_resolve, "_resolve_pending_model_leaf_reply",
                         return_value=pending_reply or (None, None)) as pend:
        out = leaf_resolve._resolve_model_leaf(req, session, MagicMock(), hints, "X", None)
    del api
    return out, hints, pend


def test_seed_valid_leaf_sets_canonical_value():
    out, hints, _ = _run_leaf("apx6000", _session())
    assert out is None and hints["_bm_model_variable_name"] == "aPX6000"


def test_seed_not_a_real_leaf_does_not_bypass_validation():
    out, hints, _ = _run_leaf("bogusNode", _session())
    assert out == {"ask": True}  # fell through to the normal question
    assert hints["_bm_model_variable_name"] == "unvalidatedCamel"  # not blessed by the seed


def test_seed_skipped_and_pending_reply_still_handled():
    session = _session(pending=["aPX6000", "aPX8000"])
    out, hints, pend = _run_leaf("aPX6000", session, pending_reply=("aPX8000", None))
    pend.assert_called_once()
    assert out is None and hints["_bm_model_variable_name"] == "aPX8000"
    assert session.pending_model_leaf_candidates == []


# ---- pick-top gating ----
def test_pick_top_off_without_resolution():
    two = ["aPX900Old", "aPX900"]
    with patch.object(bind, "get_settings", _cfg(
            cpq_model_leaf_pick_top_enabled=True, cpq_model_resolution_enabled=False)):
        assert bind.pick_top_text_match(two) is None
    with patch.object(bind, "get_settings", _cfg(
            cpq_model_leaf_pick_top_enabled=True, cpq_model_resolution_enabled=True)):
        assert bind.pick_top_text_match(two) == "aPX900Old"  # longest-name fallback


# ---- candidate ordering with both flags ----
def _cand_run(ctx_model, *flags_on):
    class _S:
        data_table_candidates_empty_on_no_match_enabled = False
        cpq_model_scope_lookups_enabled = "scope" in flags_on
        cpq_candidates_real_models_first_enabled = "first" in flags_on
    if ctx_model:
        _bind(scope=("2",))
    with patch.object(cand, "get_settings", return_value=_S()), \
            patch.object(cand, "dt_resolve_product_cpq_models_from_rows", return_value=None), \
            patch.object(cand, "dt_resolve_product_cpq_model_family", return_value=None), \
            patch.object(cand, "dt_discover_cpq_models_for_base_model", return_value=("REAL1", "REAL2")):
        return cand._cpq_model_candidates("p", 1, "X", None, base_model="T1")


def test_candidates_flags_off_unchanged():
    assert _cand_run(False) == ("APXNEXT", "APXNEXT_BOM", "REAL1", "REAL2")


def test_candidates_real_first_only():
    assert _cand_run(False, "first") == ("REAL1", "REAL2", "APXNEXT", "APXNEXT_BOM")


def test_candidates_both_flags_resolved_then_real_then_default():
    assert _cand_run(True, "scope", "first") == (
        "APX6000", "REAL1", "REAL2", "APXNEXT", "APXNEXT_BOM")


def test_prepend_log_deduped_per_turn(caplog):
    _bind(scope=("2",))
    with patch.object(cand, "get_settings", _cfg(cpq_model_scope_lookups_enabled=True)), \
            caplog.at_level(logging.INFO, logger=cand.logger.name):
        for _ in range(5):
            cand._prepend_resolved_model(("FOO",), "p", "")
    assert sum("prepended_cpq_model" in r.getMessage() for r in caplog.records) == 1


# ---- ranking: current turn beats anchor; tie rule ----
def test_turn_text_beats_anchor_question():
    anchor, turn = "quote APX 6000", "make it APX 8000"
    merged = mr.resolve_model(f"{anchor} {turn}", 1, "X", _rdb())
    assert merged.chosen.cpq_model == "APX6000"  # old behaviour: alphabetical tie -> anchor wins
    res = mr.resolve_model_turn_first(turn, anchor, 1, "X", _rdb())
    assert res.chosen.cpq_model == "APX8000"


def test_anchor_used_only_when_turn_names_no_model():
    res = mr.resolve_model_turn_first("ten radios please", "quote APX 6000", 1, "X", _rdb())
    assert res.chosen.cpq_model == "APX6000"


def test_ranking_tie_is_alphabetical_last_resort():
    # APX7000 and APX7000X share the display name and tie on every earlier step.
    res = mr.resolve_model_turn_first("APX 7000", "", 1, "X", _rdb())
    assert res.chosen.cpq_model == "APX7000" and res.deciding_step == "alphabetical"
