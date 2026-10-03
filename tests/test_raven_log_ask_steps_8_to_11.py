"""Raven structured-log placements for ask turn steps 8-11 and grid batching."""
from __future__ import annotations

import importlib
import json
import re
from types import SimpleNamespace

import pytest

import aryx.api.ask_api as api
import aryx.api.ask_core_helpers as _core

SENTINEL = "SENTINEL-CUSTOMER-TEXT-4471"
_P = "aryx.api.ask_turn_steps."
_MODULES = [
    "ask_step8_label_and_query", "ask_step8_mid_config_change", "ask_step8_pre_step5_gates",
    "ask_step8_qa_and_collision", "ask_step9_apply_result", "ask_step9_decline_multiselect",
    "ask_step9_miss_response", "ask_step9_scope_setup", "ask_step10_blocked_removal",
    "ask_step10_commit_and_drain", "ask_step10_recompute_pending", "ask_step10_rule_eval_loop",
    "ask_step10_sibling_and_multi_hint", "ask_step11_completion_responses",
    "ask_step11_on_request_response", "ask_step11_turn_cap_response", "ask_grid_batch_quantity",
]


def _m(name):
    return importlib.import_module(_P + name)


@pytest.fixture
def recs(monkeypatch):
    out: list[dict] = []

    def fake(level, criticality, message, **kw):
        out.append({"level": level, "crit": criticality, "message": message,
                    "error_code": kw.get("error_code", ""), "context": kw.get("context") or {}})
        return {}

    for name in _MODULES:
        mod = _m(name)
        monkeypatch.setattr(mod, "raven_log", fake)
        if hasattr(mod, "would_log"):
            monkeypatch.setattr(mod, "would_log", lambda lv: True)
    monkeypatch.setattr(_core, "_persist_cpq_history", lambda *a, **k: None)
    return out


def _ev(recs, event):
    return [r for r in recs if r["message"].startswith(event)]


def _no_sentinel(recs):
    assert SENTINEL not in json.dumps(recs, default=str)


def _engine(monkeypatch, **fns):
    eng = SimpleNamespace(**fns)
    monkeypatch.setattr(api, "_cpq_engine", eng)
    return eng


def _attr(vn, eid=1, label=None, options=None, select_type="single", required=True):
    return SimpleNamespace(variable_name=vn, entity_id=eid, display_label=label or vn,
                           options=options or [], select_type=select_type, required=required,
                           catalog_prefix="cp")


def _session(**kw):
    base = dict(run_id="r1", turn=3, filled={}, filled_multi={}, display_filled={},
                filled_source={}, pending_variables=[], pending_label_collision_vns=[],
                pending_label_collision_question="", pending_scope_candidates=[],
                pending_scope_attr_vn="", pending_grid_declined_vns=[], cascade_log=[],
                model_leaf_resolved=False, product_name="Prod", status="configuring",
                country="US", product_quantity=1, product_anchor_question="")
    base.update(kw)
    s = SimpleNamespace(**base)
    s.to_dict = lambda: {}
    return s


def _req(q=SENTINEL):
    return SimpleNamespace(question=q, workspace_id=1)


# ---------------------------------------------------------------- step 8

def test_label_collision_and_gate_milestone(recs, monkeypatch):
    a, b = _attr("vnA", 1, "Color"), _attr("vnB", 2, "Color")
    _engine(monkeypatch, detect_response_mode_request=lambda q: None,
            detect_label_collision=lambda q, at: [a, b])
    monkeypatch.setattr(_m("ask_step8_label_and_query"), "_narrow_label_collision", lambda q, c: c)
    from aryx.api.ask_turn_steps.ask_step8_pre_step5_gates import _step8_run_pre_step5_gates
    res, mode = _step8_run_pre_step5_gates(_req(), _session(), [a, b], None, [], [], [], [], None, "cp")
    assert res is not None and mode is None
    (c,) = _ev(recs, "ask.collision.label")
    assert c["level"] == "DEBUG" and c["context"]["selected_option"] == "label_collision"
    assert c["context"]["candidate_fields"] == ["vnA", "vnB"]
    (g,) = _ev(recs, "ask.preamble.gate pre-step5")
    assert g["level"] == "INFO" and g["context"]["selected_option"] == "label_collision_or_query"
    assert _ev(recs, "ask.preamble.mode_request")[0]["context"]["reason_code"] == "NO_MODE_REQUEST"
    _no_sentinel(recs)


def test_no_gate_matched_and_no_change(recs, monkeypatch):
    _engine(monkeypatch, detect_response_mode_request=lambda q: None,
            detect_label_collision=lambda q, at: [], detect_attr_query=lambda q, at: None,
            _OPTIONS_KEYWORDS=("options",), detect_qa_question=lambda *a, **k: False,
            detect_change_requests_multi=lambda *a, **k: [],
            detect_change_request=lambda *a, **k: None,
            detect_change_target_without_value=lambda *a, **k: None)
    from aryx.api.ask_turn_steps.ask_step8_pre_step5_gates import _step8_run_pre_step5_gates
    s = _session(pending_variables=["vnA"])
    res, _ = _step8_run_pre_step5_gates(_req(), s, [_attr("vnA")], None, [], [], [], [], None, "cp")
    assert res is None
    assert _ev(recs, "ask.qa.strict")[0]["context"]["reason_code"] == "NOT_QA_QUESTION"
    ch = _ev(recs, "ask.change.mid_config no single change")[0]["context"]
    assert ch["reason_code"] == "NO_CHANGE_REQUEST" and ch["selected_option"] == "continue"
    assert _ev(recs, "ask.preamble.gate no pre-step5")[0]["context"]["reason_code"] == "NO_GATE_MATCHED"
    _no_sentinel(recs)


def test_mid_config_mode_request_skip(recs, monkeypatch):
    _engine(monkeypatch)
    from aryx.api.ask_turn_steps.ask_step8_mid_config_change import _step8_mid_config_change
    assert _step8_mid_config_change(_req(), _session(), [], [], [], [], None, "cp", "json") is None
    (r,) = _ev(recs, "ask.change.mid_config skipped")
    assert r["context"]["reason_code"] == "MODE_REQUEST"


def test_pending_collision_unrecognized_and_missing_attr_warn(recs, monkeypatch):
    mod = _m("ask_step8_qa_and_collision")
    _engine(monkeypatch)
    monkeypatch.setattr(mod._ask_decline_reply_and_label_collision_llm_module,
                        "_llm_resolve_label_collision", lambda *a, **k: None)
    s = _session(pending_label_collision_vns=["vnA", "vnB"])
    assert mod._step8_qa_and_pending_collision(
        _req(), s, [_attr("vnA"), _attr("vnB", 2)], None, [], [], [], None, "cp", None) is None
    (r,) = _ev(recs, "ask.collision.pending system collision")
    assert r["context"]["match_tier"] == "llm_no_match"
    assert r["context"]["selected_option"] == "clear_stale_collision"
    assert s.pending_label_collision_vns == []
    assert mod._resolve_pending_question_collision(
        _req(), _session(), [], "vnZ", [], [], [], None, "cp") is None
    (w,) = _ev(recs, "ask.collision.pending resolved field not in catalog")
    assert w["level"] == "WARN" and w["error_code"] == "ARYX_ASK_COLLISION_ATTR_MISSING"
    _no_sentinel(recs)


def test_pending_collision_index_tier(recs, monkeypatch):
    mod = _m("ask_step8_qa_and_collision")
    monkeypatch.setattr(mod, "_resolve_pending_question_collision", lambda *a, **k: {"ok": 1})
    _engine(monkeypatch)
    s = _session(pending_label_collision_vns=["vnA", "vnB"])
    assert mod._step8_qa_and_pending_collision(
        _req("2"), s, [], None, [], [], [], None, "cp", None) == {"ok": 1}
    (r,) = _ev(recs, "ask.collision.pending system collision")
    assert r["context"]["match_tier"] == "index" and r["context"]["resolved_field"] == "vnB"


# ---------------------------------------------------------------- step 9

def test_apply_result_validation_reject_and_commit(recs, monkeypatch):
    mod = _m("ask_step9_apply_result")
    monkeypatch.setattr(mod, "clear_pending_scope", lambda s: None)
    monkeypatch.setattr(mod, "push_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_invalidate_stale_base_model", lambda *a, **k: None)
    pa, dep = _attr("vnA", 1), _attr("vnDep", 2)
    warn = {"vnA": SENTINEL}
    _engine(monkeypatch, apply_validation_rules=lambda *a, **k: warn,
            next_question_prompt=lambda *a, **k: "q",
            find_cascade_dependents=lambda *a, **k: [2])
    s = _session(filled={"vnDep": "x"})
    assert mod._step9_apply_pending_result(
        _req(), s, [pa, dep], pa, "vnA", ("v", SENTINEL), [], [], [], [], [], None) is not None
    r = _ev(recs, "ask.reply.apply validation")[-1]
    assert r["context"]["selected_option"] == "reject_with_warning"
    warn.clear()
    assert mod._step9_apply_pending_result(
        _req(), s, [pa, dep], pa, "vnA", ("v", SENTINEL), [], [], [], [], [], None) is None
    (c,) = _ev(recs, "ask.reply.apply pending answer committed")
    assert c["context"]["pending_field"] == "vnA" and c["context"]["cleared_dependents"] == ["vnDep"]
    _no_sentinel(recs)


def test_decline_multiselect(recs, monkeypatch):
    _engine(monkeypatch, resolve_array_grid_links=lambda at: {})
    from aryx.api.ask_turn_steps.ask_step9_decline_multiselect import _step9_decline_optional_multiselect
    s = _session()
    _step9_decline_optional_multiselect(s, _attr("vnM", select_type="multi"), "vnM", None, [])
    (r,) = _ev(recs, "ask.reply.decline")
    assert r["context"]["selected_option"] == "clear_to_empty"
    assert r["context"]["reason_code"] == "FIRST_DECLINE" and r["context"]["match_tier"] == "explicit_decline"


def test_miss_response_full_reask_and_low_confidence(recs, monkeypatch):
    mod = _m("ask_step9_miss_response")
    monkeypatch.setattr(mod, "_remember_attr_scope", lambda *a, **k: None)
    monkeypatch.setattr(mod, "log_scope_lost", lambda **k: None)
    monkeypatch.setattr(mod, "set_pending_scope", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_compose_disambiguation_question", lambda *a, **k: "ans")
    _engine(monkeypatch, disambiguated_label=lambda a, at: "Label",
            next_question_prompt=lambda *a, **k: "opts")
    pa = _attr("vnA", options=[SimpleNamespace(item_value="x", display_name="x")])
    out = mod._step9_options_miss_response(_req(), _session(), [pa], pa, "vnA", ["x"])
    assert SENTINEL in out["answer"]
    (r,) = _ev(recs, "ask.reply.miss invalid answer")
    assert r["context"]["selected_option"] == "full_options_reask" and r["context"]["pending_field"] == "vnA"
    mod._step9_low_confidence_response(_req(), _session(), [pa], pa, "vnA", ["x", "y"])
    (lc,) = _ev(recs, "ask.reply.miss low-confidence")
    assert lc["context"]["match_tier"] == "llm_low_confidence" and lc["context"]["candidate_count"] == 2
    _no_sentinel(recs)


def test_scope_setup_match_tier(recs, monkeypatch):
    mod = _m("ask_step9_scope_setup")
    monkeypatch.setattr(mod, "_resolve_scope_reply",
                        lambda *a, **k: SimpleNamespace(matched="x", tier="fuzzy"))
    _engine(monkeypatch, apply_constraint_rules=lambda *a, **k: {},
            _apply_series_mapping_exclusions=lambda *a, **k: None,
            disambiguated_label=lambda a, at: "L")
    pa = _attr("vnA", options=[SimpleNamespace(item_value="x", display_name="x")])
    s = _session(pending_scope_candidates=["x"], pending_scope_attr_vn="vnA")
    out = mod._step9_scope_and_constraint_setup(_req(), s, [pa], pa, "vnA", {}, [], None, "cp")
    assert out[0] is None and out[5] == "x"
    assert _ev(recs, "ask.reply.scope pending constraint")[0]["context"]["selected_option"] == "scope_resolve"
    (r,) = _ev(recs, "ask.reply.scope scoped reply match tier")
    assert r["context"]["match_tier"] == "fuzzy" and r["context"]["reason_code"] == "SCOPE_MATCHED"
    _no_sentinel(recs)


# ---------------------------------------------------------------- step 10

def test_blocked_removal_skip_and_pronoun_gap(recs, monkeypatch):
    mod = _m("ask_step10_blocked_removal")
    assert mod._step10_blocked_removal_gap(
        _req(), _session(pending_variables=["a"]), [], [], [], [], None, "cp", None) is None
    assert _ev(recs, "ask.removal.blocked_gap skipped")[0]["context"]["reason_code"] == "PENDING_PRESENT"
    _engine(monkeypatch, detect_multi_select_removal=lambda *a, **k: None,
            _REMOVE_VERB_RE=re.compile("remove"),
            resolve_array_grid_links=lambda at: {"sel": {"known": "qty"}})
    monkeypatch.setattr(mod._ask_handle_multi_select_removal_module,
                        "_handle_multi_select_removal", lambda *a, **k: {"done": 1})
    s = _session(filled_multi={"sel": ["gapval"]})
    assert mod._step10_blocked_removal_gap(
        _req(f"remove it {SENTINEL}"), s, [_attr("sel")], [], [], [], None, "cp", None) == {"done": 1}
    (r,) = _ev(recs, "ask.removal.blocked_gap pronoun")
    assert r["context"]["selected_option"] == "pronoun_gap_removal" and r["context"]["gap_count"] == 1
    _no_sentinel(recs)


def test_commit_and_drain_counts(recs, monkeypatch):
    mod = _m("ask_step10_commit_and_drain")
    monkeypatch.setattr(mod, "clear_queue_vn", lambda *a: None)
    monkeypatch.setattr(mod, "drain_intent_queue_into_pending", lambda s, p, v: [*p, _attr("q2")])
    s = _session()
    note, pending = mod._step10_commit_and_drain(
        s, [_attr("a")], [], {"a": "1"}, {"a": "1"}, [_attr("a")], {}, {}, {}, "a", 0.0)
    assert note == "" and len(pending) == 2
    (r,) = _ev(recs, "ask.recompute.commit")
    c = r["context"]
    assert c["selected_option"] == "drained" and c["changed_fields"] == ["a"]
    assert (c["pending_before_drain"], c["pending_after_drain"]) == (1, 2)


def test_recompute_pending_counts(recs, monkeypatch):
    mod = _m("ask_step10_recompute_pending")
    monkeypatch.setattr(mod, "get_settings", lambda: SimpleNamespace(cpq_post_loop_timeout_enabled=False))
    monkeypatch.setattr(mod, "grid_narrow_kwargs", lambda *a: {})
    a, b = _attr("a"), _attr("b", 2)
    _engine(monkeypatch, evaluate_rules_loop=lambda *x, **k: ([a, b], {"a": "1"}, {}, {}),
            governed_target_ids=lambda *x: set(), rule_governed_ids=lambda *x: {1},
            _load_layout_full_order=lambda *x: [], load_layout_display_order=lambda *x: [],
            auto_fill=lambda *x, **k: ({"a": "1"}, {}, [b]),
            append_pending_grid_quantities=lambda p, *x, **k: [*p, a])
    out = mod._step10_recompute_pending(
        {}, [a, b], _session(), [], [], [], None, {}, set(), set(), [], _req(), "cp")
    assert len(out[3]) == 2
    (r,) = _ev(recs, "ask.recompute.pending")
    c = r["context"]
    assert c["selected_option"] == "inline_post_loop" and c["pending_count"] == 2
    assert c["grid_added_count"] == 1 and c["noise_dropped_count"] == 0


def test_rule_eval_loop_exit_reasons(recs, monkeypatch):
    mod = _m("ask_step10_rule_eval_loop")
    _engine(monkeypatch, resolve_always_ask_skips=lambda *a: set())
    monkeypatch.setattr(mod, "_step10_blocked_removal_gap", lambda *a: {"early": 1})
    assert mod._step10_run_rule_eval_loop(
        _req(), _session(), [], {}, [], [], [], [], None, "cp", set(), None, None)[0] == {"early": 1}
    assert _ev(recs, "ask.recompute.loop exited")[0]["context"]["reason_code"] == "BLOCKED_REMOVAL_HANDLED"
    monkeypatch.setattr(mod, "_step10_blocked_removal_gap", lambda *a: None)
    monkeypatch.setattr(mod, "_step10_recompute_pending", lambda *a: ([], {}, {}, [], {}, set()))
    monkeypatch.setattr(mod, "_step10_enforce_siblings_and_multi_hint", lambda *a: ([], {}, {}, [], {}, set()))
    monkeypatch.setattr(mod, "_step10_commit_and_drain", lambda *a: ("", []))
    mod._step10_run_rule_eval_loop(_req(), _session(), [], {}, [], [], [], [], None, "cp", set(), None, None)
    (r,) = _ev(recs, "ask.recompute.loop rule eval finished")
    assert r["context"]["reason_code"] == "NOTHING_PENDING"


def test_sibling_and_multi_hint_second_recompute(recs, monkeypatch):
    mod = _m("ask_step10_sibling_and_multi_hint")
    a, b = _attr("a"), _attr("b", 2)
    _engine(monkeypatch, _rule_forced_from_active_decision_vns=lambda *x: set(),
            _CONFIG_DATA_ACTIVE_SOURCES=(), _data_table_forced_vns=lambda *x, **k: set(),
            enforce_exclusive_sibling_families=lambda *x, **k: [a, b])
    monkeypatch.setattr(mod, "_relevant_intent_candidates", lambda *x, **k: [a, b])
    monkeypatch.setattr(mod, "_llm_extract_multi_attr_hints", lambda *x: {"a": SENTINEL})
    monkeypatch.setattr(mod, "_step10_recompute_pending", lambda *x: ([], {}, {}, [], {}, set()))
    mod._step10_enforce_siblings_and_multi_hint(
        _req(), _session(), [a, b], {}, [a, b], {}, {}, [a, b], {}, set(), [], [], [], None,
        {}, set(), set(), [], "cp")
    assert _ev(recs, "ask.recompute.siblings")[0]["context"]["selected_option"] == "multi_hint_check"
    assert _ev(recs, "ask.recompute.multi_hint candidate")[0]["context"]["candidate_count"] == 2
    (r,) = _ev(recs, "ask.recompute.multi_hint second")
    assert r["context"]["selected_option"] == "second_recompute" and r["context"]["hint_fields"] == ["a"]
    _no_sentinel(recs)


# ---------------------------------------------------------------- step 11

def test_completion_sub_builders(recs, monkeypatch):
    mod = _m("ask_step11_completion_responses")
    _engine(monkeypatch, unresolved_grid_quantity_options=lambda *a: [("Mount", "Opt")])
    assert mod._step11_grid_gap_response(_session(), [], "") is not None
    assert _ev(recs, "ask.response.grid_gap")[0]["context"]["selected_option"] == "grid_gap_block"
    monkeypatch.setattr(mod, "_reask_stale_constraint_violations", lambda *a: None)
    assert mod._step11_stale_reask_response(_req(), _session(), [], [], None, "cp", "") is None
    assert _ev(recs, "ask.response.stale_reask")[0]["context"]["reason_code"] == "NO_STALE_VIOLATION"
    monkeypatch.setattr(mod, "_cpq_summary_text", lambda *a, **k: "sum")
    s = _session()
    mod._step11_completion_response(_req(), s, [], {"a": "1"}, set(), "")
    (r,) = _ev(recs, "ask.response.completion")
    assert r["context"]["status"] == "awaiting_approval" and s.status == "awaiting_approval"
    _no_sentinel(recs)


def test_on_request_format_a_and_turn_cap(recs, monkeypatch):
    mod = _m("ask_step11_on_request_response")
    monkeypatch.setattr(mod, "_grid_batch_pending_answer", lambda *a: None)
    monkeypatch.setattr(mod, "_label_collision_for", lambda *a: [])
    monkeypatch.setattr(mod, "_remember_attr_scope", lambda *a, **k: None)
    _engine(monkeypatch, build_context_sentence=lambda *a, **k: "",
            next_question_prompt=lambda *a, **k: "q")
    a = _attr("a")
    assert mod._step11_on_request_response(
        _req(), _session(), [a], [a], {}, {}, [a], {1: ["x"]}, set(), [], [], [], [], None,
        "cp", None, "") == "q"
    (r,) = _ev(recs, "ask.response.on_request")
    assert r["context"]["selected_option"] == "format_a" and r["context"]["constrained_count"] == 1
    tc = _m("ask_step11_turn_cap_response")
    monkeypatch.setattr(tc, "_label_collision_for", lambda *a: [])
    tc._step11_turn_cap_response(_req(), _session(), [a], [a], {}, [])
    (t,) = _ev(recs, "ask.response.turn_cap")
    assert t["context"]["reason_code"] == "TURN_CAP_REACHED" and t["context"]["unresolved_count"] == 1
    _no_sentinel(recs)


# ---------------------------------------------------------------- grid batch

def test_grid_batch_reply_and_mismatch(recs, monkeypatch):
    mod = _m("ask_grid_batch_quantity")
    q1, q2 = _attr("q1", 2, "Q1"), _attr("q2", 3, "Q2")
    _engine(monkeypatch, resolve_array_grid_links=lambda at: {"sel": {"o1": "q1", "o2": "q2"}},
            parse_grid_batch_quantities=lambda c, q: {"q1": 3},
            grid_batch_count_mismatch=lambda c, q: 1)
    s = _session(pending_variables=["q1", "q2"])
    assert mod._try_apply_grid_quantities_batch_reply(SENTINEL, s, [q1, q2]) == {"q1"}
    (r,) = _ev(recs, "ask.grid_batch.reply")
    assert r["context"]["reason_code"] == "PARTIAL_RESOLVED" and r["context"]["resolved_fields"] == ["q1"]
    s2 = _session(pending_variables=["q1", "q2"])
    assert mod._grid_batch_count_mismatch_message(_req(), s2, [q1, q2]) is not None
    (m,) = _ev(recs, "ask.grid_batch.mismatch positional")
    assert m["context"]["selected_option"] == "count_mismatch_reask" and m["context"]["given_count"] == 1
    _no_sentinel(recs)
