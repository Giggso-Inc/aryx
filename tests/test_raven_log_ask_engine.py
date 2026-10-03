"""Raven structured-log placements for the CPQ ask engine (area ``ask_engine``, G1-G8, R7, R11)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from aryx import raven_log as rl
from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption
from aryx.cpq.state.state_rules import RecommendationRule

_MODULES = [
    "aryx.cpq.auto_fill_stages.fill_log",
    "aryx.cpq.auto_fill_stages.coordinator",
    "aryx.cpq.rules_loop.rules_loop",
    "aryx.cpq.rules_loop.rules_loop_pass_early",
    "aryx.cpq.rules_loop.rules_loop_pass_late",
    "aryx.cpq.rule_trace.rule_trace",
    "aryx.cpq.rdb.rdb_oracle",
    "aryx.cpq.data_table_bridge.candidates",
    "aryx.cpq.data_table_bridge.conflicts",
]


@pytest.fixture
def recs(monkeypatch):
    """Capture every record emitted by the ask-engine modules (all levels)."""
    import importlib
    out: list[dict] = []

    def fake(level, criticality, message, **kw):
        out.append({"level": level, "crit": criticality, "message": message,
                    "error_code": kw.get("error_code", ""), "context": kw.get("context") or {},
                    "trace_id": rl.current_run_id()})
        return {}

    for name in _MODULES:
        mod = importlib.import_module(name)
        if hasattr(mod, "raven_log"):
            monkeypatch.setattr(mod, "raven_log", fake)
        if hasattr(mod, "would_log"):
            monkeypatch.setattr(mod, "would_log", lambda lv: True)
    rl.bind_run_id("run-ask-1")
    fill_log.set_pass(None)
    yield out
    rl.bind_run_id("")


def _ev(recs, event):
    return [r for r in recs if r["message"].startswith(event)]


def _menu(*vals):
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(vals, 1)]


def _attr(eid, vn, options=None, select_type="single", default=""):
    return ConfigAttr(entity_id=eid, variable_name=vn, display_label=vn, required=False,
                      default_value=default, options=options or [], select_type=select_type)


def test_loop_emits_attribute_set_and_stop_records(recs):
    a = _attr(1, "flavor", _menu("A"))
    b = _attr(2, "recTarget", _menu("X", "Y"))
    rec = RecommendationRule(rule_name="recommend Y", condition_attr_id=1, condition_value="A",
                             target_attr_id=2, recommended_value="Y")
    CpqEngine().evaluate_rules_loop([a, b], {}, {}, [], [rec], [], filled_source={})
    attr_recs = _ev(recs, "ask.fill.attribute")
    assert {r["context"]["object_id"] for r in attr_recs} >= {"flavor"}
    assert all("stage_trail" in r["context"] and "decided_by" in r["context"] for r in attr_recs)
    assert any(r["context"]["pass"] == 0 for r in attr_recs)
    sets = _ev(recs, "ask.fill.set")
    assert sets and all(r["level"] == "DEBUG" for r in sets)
    assert _ev(recs, "ask.rules_loop.stopped")
    assert _ev(recs, "ask.rules_loop.break_check")
    assert all(r["trace_id"] == "run-ask-1" for r in recs)


def test_overwrite_warns_with_old_and_new_source(recs):
    ctx = SimpleNamespace(filled={"antenna": "WHIP (STANDARD)"}, filled_multi={},
                          sources={"antenna": "default_first_available"})
    attr = _attr(1, "antenna", _menu("WHIP (STANDARD)", "STANDARD"))
    fill_log.set_pass(2)
    fill_log.log_write(ctx, attr, "antenna", "STANDARD", "Standard", "blind_pick_rule_governed",
                       "blind_pick_rule_governed")
    w = _ev(recs, "ask.fill.overwritten")
    assert len(w) == 1 and w[0]["level"] == "WARN" and w[0]["error_code"] == "ARYX_ASK_FILL_OVERWRITTEN"
    c = w[0]["context"]
    assert (c["old_source"], c["new_source"], c["pass"]) == (
        "default_first_available", "blind_pick_rule_governed", 2)
    assert c["value"] == "STANDARD"  # enumerated value is logged (D6)


def test_same_value_rewrite_is_debug_only(recs):
    ctx = SimpleNamespace(filled={"v": "A"}, filled_multi={}, sources={"v": "user"})
    fill_log.log_write(ctx, _attr(1, "v", _menu("A")), "v", "A", "A", "default", "commit_value")
    assert not _ev(recs, "ask.fill.overwritten")
    assert _ev(recs, "ask.fill.set")[0]["context"]["result"] == "rewritten_same"


def test_free_text_value_is_hashed_never_logged(recs):
    ctx = SimpleNamespace(filled={}, filled_multi={}, sources={})
    fill_log.log_write(ctx, _attr(1, "notes"), "notes", "SECRET-CUSTOMER-TEXT", "x", "hint", "commit_value")
    blob = json.dumps(recs)
    assert "SECRET-CUSTOMER-TEXT" not in blob
    c = _ev(recs, "ask.fill.set")[0]["context"]
    assert c["value_kind"] == "free_text" and c["value_len"] == 20 and len(c["value_hash"]) == 12


def test_base_model_placeholder_warns(recs):
    ctx = SimpleNamespace(filled={}, filled_multi={}, sources={})
    attr = _attr(1, "modelSelectionbaseModel_astro", _menu("*", "APX900"))
    fill_log.log_write(ctx, attr, "modelSelectionbaseModel_astro", "*", "*", "rule", "apply_recommendation_rules")
    w = _ev(recs, "ask.base_model.write")
    assert w[0]["level"] == "WARN" and w[0]["error_code"] == "ARYX_ASK_BASE_MODEL_PLACEHOLDER"
    assert w[0]["context"]["is_wildcard"] is True
    fill_log.log_write(SimpleNamespace(filled={}, filled_multi={}, sources={}), attr,
                       "modelSelectionbaseModel_astro", "APX900", "APX900", "rule", "commit_value")
    assert _ev(recs, "ask.base_model.write")[1]["level"] == "DEBUG"


def test_pruned_is_info_for_model_context_else_debug(recs):
    fill_log.log_pruned("_bm_model_variable_name", "NOT_GOVERNED", "t")
    fill_log.log_pruned("ordinary", "NOT_GOVERNED", "t")
    p = _ev(recs, "ask.attr.pruned")
    assert [r["level"] for r in p] == ["INFO", "DEBUG"]
    assert p[0]["context"]["is_model_context"] is True


def test_static_model_fallback_warns_once_per_turn(recs, monkeypatch):
    from aryx.cpq.data_table_bridge import candidates as c
    monkeypatch.setattr(c, "dt_resolve_product_cpq_models_from_rows", lambda *a, **k: None)
    monkeypatch.setattr(c, "dt_resolve_product_cpq_model_family", lambda *a, **k: None)
    monkeypatch.setattr(c, "get_settings", lambda: SimpleNamespace(data_table_candidates_empty_on_no_match_enabled=False,
                                                                   cpq_model_scope_lookups_enabled=False,
                                                                   cpq_candidates_real_models_first_enabled=False))
    assert c._cpq_model_candidates("APX 900", 1) == ("APXNEXT", "APXNEXT_BOM")
    c._cpq_model_candidates("APX 900", 1)
    warns = _ev(recs, "ask.model.fallback_static")
    assert len(warns) == 1 and warns[0]["error_code"] == "ARYX_ASK_MODEL_FALLBACK_STATIC"
    assert warns[0]["context"]["static_fallback_used"] is True
    assert len(_ev(recs, "ask.model.candidates")) == 1  # second call is DEBUG
    monkeypatch.setattr(c, "dt_resolve_product_cpq_models_from_rows", lambda *a, **k: ("APX900",))
    c._cpq_model_candidates("APX 900", 1)
    hit = _ev(recs, "ask.model.candidates")[-1]
    assert hit["context"]["tier"] == "tier1_text_match" and hit["context"]["static_fallback_used"] is False


def test_datatable_discarded_warns_when_values_dropped(recs, monkeypatch):
    from aryx.cpq.data_table_bridge import conflicts as k
    monkeypatch.setattr(k, "resolve_base_model_vn", lambda *a, **kw: "bm")
    monkeypatch.setattr(k, "_cpq_model_candidates", lambda *a, **kw: ("APXNEXT",))
    monkeypatch.setattr(k, "dt_resolve_whitelist_values", lambda *a, **kw: ["a", "b", "c"])
    opts = _menu("a", "b", "c")
    assert k._resolve_via_data_tables("ant", {"bm": "X"}, opts, 1) is None
    w = _ev(recs, "ask.datatable.discarded")
    assert w[0]["level"] == "WARN" and w[0]["error_code"] == "ARYX_ASK_DATATABLE_DISCARDED"
    assert w[0]["context"]["candidate_count"] == 3
    monkeypatch.setattr(k, "dt_resolve_whitelist_values", lambda *a, **kw: ["b"])
    assert k._resolve_via_data_tables("ant", {"bm": "X"}, opts, 1).item_value == "b"
    assert _ev(recs, "ask.datatable.lookup")[-1]["context"]["outcome"] == "single_match"
    assert k._resolve_narrowed_legal_values("ant", {"bm": "X"}, 1) == ["b"]
    assert _ev(recs, "ask.datatable.lookup")[-1]["context"]["legal_set_state"] == "list"
    assert k._resolve_narrowed_legal_values("ant", {}, 1) is None
    assert _ev(recs, "ask.datatable.lookup")[-1]["context"]["legal_set_state"] == "unknown_none"


def test_rdb_oracle_read_failure_is_logged_not_raised(recs, monkeypatch):
    from aryx.cpq.rdb.rdb_oracle import OracleCpqRdb
    rdb = OracleCpqRdb.__new__(OracleCpqRdb)

    def boom(self):
        raise RuntimeError("ORA-12345 secret-dsn")

    monkeypatch.setattr(OracleCpqRdb, "_connection", boom)
    assert rdb.fetch_entity_attributes([1], 1) == {}
    e = _ev(recs, "ask.rdb.read_failed")[0]
    assert e["level"] == "ERROR" and e["error_code"] == "ARYX_ASK_RDB_READ_FAILED"
    assert e["context"]["dependency_name"] == "oracle_adb"
    assert e["context"]["operation"] == "fetch_entity_attributes"
    assert e["context"]["error_class"] == "RuntimeError"
    assert "secret-dsn" not in json.dumps(recs)


def test_rule_trace_fire_attribution_and_durable_failure(recs, monkeypatch, tmp_path):
    from aryx.cpq.rule_trace import rule_trace as rt
    from aryx.cpq.logging_context import set_run_id
    set_run_id("trace-run-1")
    rt.bind_context(1, "cat")
    fill_log.bind_sources({"tgt": "default"})

    class Boom:
        def open_session(self, *a, **k):
            raise RuntimeError("down")

        append_entry = open_session

    monkeypatch.setattr(rt, "_store", lambda: Boom())
    monkeypatch.setattr(rt, "_trace_dir", lambda: tmp_path)
    try:
        rt.record_fire(rule_type="recommendation", rule_id="Set Base Model", attr="tgt", outcome="set=Y")
    finally:
        set_run_id("")
    fired = _ev(recs, "ask.rule.fired")[0]["context"]
    assert fired["rule_name"] == "Set Base Model" and fired["ref_id"] is None
    assert (fired["target_attribute"], fired["old_source"], fired["new_source"]) == ("tgt", "default", "rule")
    failed = _ev(recs, "ask.rule_trace.durable_failed")
    assert {f["context"]["operation"] for f in failed} == {"open_session", "append_entry"}
    assert all(f["error_code"] == "ARYX_ASK_RULE_TRACE_FAILED" and f["level"] == "WARN" for f in failed)


def test_turn_state_record_uses_value_rules(recs):
    sess = SimpleNamespace(run_id="r1", filled={"region": "NA", "note": "TOP-SECRET"},
                           filled_multi={}, filled_source={"region": "user", "note": "hint"},
                           pending_variables=["x"])
    attrs = [_attr(1, "region", _menu("NA", "EU")), _attr(2, "note")]
    ctxd = fill_log.build_turn_state_record(sess, attrs)
    assert ctxd["filled_source"] == {"region": "user", "note": "hint"}
    assert ctxd["values"]["region"] == "NA"
    assert "TOP-SECRET" not in json.dumps(ctxd) and ctxd["values"]["note"]["value_kind"] == "free_text"
    assert _ev(recs, "ask.turn.state")[0]["level"] == "DEBUG"


def test_real_wrapper_records_carry_bound_trace_id(monkeypatch, capsys):
    monkeypatch.setenv("ARYX_RAVEN_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ARYX_RAVEN_LOG_ENABLED", "true")
    rl.reload_config()
    rl.bind_run_id("real-run-9")
    try:
        ctx = SimpleNamespace(filled={}, filled_multi={}, sources={})
        fill_log.log_write(ctx, _attr(1, "v", _menu("A")), "v", "A", "A", "default", "commit_value")
    finally:
        rl.bind_run_id("")
        monkeypatch.delenv("ARYX_RAVEN_LOG_LEVEL")
        rl.reload_config()
    line = [l for l in capsys.readouterr().out.splitlines() if "ask.fill.set" in l][0]
    assert json.loads(line)["trace_id"] == "real-run-9"
