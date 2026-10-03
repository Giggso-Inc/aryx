"""Raven structured-log placements for ask turn steps 1, 2 and 6-8 (area C)."""
from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest

from aryx.api import ask_api

SENTINEL = "SENTINEL-CUSTOMER-TEXT-4471"
_PKG = "aryx.api.ask_turn_steps."
_MODULES = [
    "ask_step1_product_family_prompt", "ask_step2_anchor_gates", "ask_step2_catalog_hints",
    "ask_step2_pending_change_no_value", "ask_step2_resolve_and_load",
    "ask_step2_rule_consistency", "ask_step678_activation_and_clear",
    "ask_step678_bulk_and_removal", "ask_step678_change_collision",
    "ask_step678_change_collision_detect", "ask_step678_change_dispatch",
    "ask_step678_json_and_approval", "ask_step678_llm_fallback",
    "ask_step678_no_value_and_nudge", "ask_step678_options_collision",
    "ask_step678_review_status",
]


def _mod(name):
    return importlib.import_module(_PKG + name)


@pytest.fixture
def recs(monkeypatch):
    out: list[dict] = []

    def fake(level, criticality, message, **kw):
        out.append({"level": level, "crit": criticality, "message": message,
                    "error_code": kw.get("error_code", ""), "context": kw.get("context") or {}})
        return {}

    for name in _MODULES:
        mod = _mod(name)
        monkeypatch.setattr(mod, "raven_log", fake)
        if hasattr(mod, "would_log"):
            monkeypatch.setattr(mod, "would_log", lambda level: True)
    monkeypatch.setattr("aryx.api.ask_core_helpers._persist_cpq_history", lambda *a, **k: None)
    yield out


def _ev(recs, event):
    return [r for r in recs if r["message"].startswith(event)]


def _no_sentinel(recs):
    assert recs
    assert SENTINEL not in json.dumps(recs, default=str)


def _session(**kw):
    base = dict(turn=3, run_id="r1", status="configuring", product_name="APX", country="US",
                pending_anchor="", pending_switch_question="", negated_vns=[], filled={},
                filled_multi={}, display_filled={}, filled_source={}, pending_variables=[],
                pending_change_collision_vns=[], pending_change_collision_question="",
                pending_label_collision_vns=[], pending_label_collision_question="",
                pending_change_no_value_vn="", model_leaf_resolved=False,
                product_quantity=1, product_anchor_question="")
    base.update(kw)
    s = SimpleNamespace(**base)
    s.to_dict = lambda: {}
    return s


def _req(q=f"quote {SENTINEL}"):
    return SimpleNamespace(question=q, workspace_id="ws1")


def _attr(vn, **kw):
    return SimpleNamespace(variable_name=vn, display_label=kw.get("label", vn),
                           entity_id=vn, select_type="single", options=[], catalog_prefix="cat")


class _Eng:
    """Minimal engine stub; tests override attributes as needed."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return lambda *a, **k: None


# ------------------------------------------------------------------ step 1

@pytest.mark.parametrize("suggestions,families,option,level", [
    (["SVX"], ["SVX", "APX"], "single_suggestion", "DEBUG"),
    (["SVX", "APX"], ["SVX", "APX"], "did_you_mean_suggestions", "INFO"),
    ([], [], "ask_product_family", "INFO"),
])
def test_family_prompt_branches(recs, monkeypatch, suggestions, families, option, level):
    eng = _Eng(list_ingested_families=lambda *a: families,
               ingested_product_alias_map=lambda *a: {},
               suggest_product_candidates=lambda *a, **k: list(suggestions))
    monkeypatch.setattr(ask_api, "_cpq_engine", eng)
    m = _mod("ask_step1_product_family_prompt")
    monkeypatch.setattr(m, "set_pending_scope", lambda *a, **k: None)
    m._build_product_family_prompt_or_resolve(
        _req(f"I need a quote for some radios please {SENTINEL}"), _session(), None)
    rec = _ev(recs, "ask.anchor.family_prompt")[-1]
    assert rec["level"] == level and rec["context"]["selected_option"] == option
    _no_sentinel(recs)


# ------------------------------------------------------------------ step 2

def _patch_gates(monkeypatch, attrs):
    m = _mod("ask_step2_anchor_gates")
    monkeypatch.setattr(ask_api, "_cpq_engine", _Eng(load_product_config=lambda *a: (attrs, "APX")))
    monkeypatch.setattr(m, "_log_turn_intent_diagnostics", lambda *a: None)
    monkeypatch.setattr(m, "_seed_product_select_from_anchor", lambda *a: None)
    monkeypatch.setattr(m, "_check_mid_turn_switch_redetection", lambda *a: None)
    return m


def test_anchor_gate_asks_country(recs, monkeypatch):
    m = _patch_gates(monkeypatch, [_attr("a")])
    resp, _, _ = m._step2_resolve_product_and_gates(_req(), _session(country=""), None, {}, True, False)
    assert resp["tools_called"] == ["cpq_anchor_validation()"]
    rec = _ev(recs, "ask.preamble.gate")[-1]
    assert rec["level"] == "INFO" and rec["context"]["reason_code"] == "COUNTRY_MISSING"
    assert _ev(recs, "ask.preamble.product_config")
    _no_sentinel(recs)


def test_anchor_gate_empty_catalog_warns(recs, monkeypatch):
    m = _patch_gates(monkeypatch, [])
    resp, _, _ = m._step2_resolve_product_and_gates(_req(), _session(), None, {}, False, False)
    assert resp == {}
    rec = _ev(recs, "ask.preamble.gate")[-1]
    assert rec["level"] == "WARN" and rec["error_code"] == "ARYX_ASK_EMPTY_CATALOG"
    _no_sentinel(recs)


def test_catalog_hints_names_only(recs, monkeypatch):
    monkeypatch.setattr(ask_api, "_cpq_engine", _Eng(
        extract_catalog_hints=lambda q, a: ({"colorVn": f"free {SENTINEL}"}, {"negVn"}),
        extract_flag_hints=lambda *a: {}))
    m = _mod("ask_step2_catalog_hints")
    monkeypatch.setattr(m.rule_trace, "bind_context", lambda *a: None)
    hints: dict = {}
    m._step2_catalog_hints_and_negation(_req(), _session(), [_attr("a")], hints, "")
    rec = _ev(recs, "ask.preamble.catalog_hints")[-1]
    assert rec["context"]["catalog_hint_vns"] == ["colorVn"]
    assert rec["context"]["negated_now_vns"] == ["negVn"]
    _no_sentinel(recs)


def test_pending_change_no_value_topic_switch(recs, monkeypatch):
    monkeypatch.setattr(ask_api, "_cpq_engine", _Eng())
    m = _mod("ask_step2_pending_change_no_value")
    monkeypatch.setattr(m, "_pending_reply_is_topic_switch", lambda *a: True)
    out = m._resolve_pending_change_no_value(
        _req(), _session(pending_change_no_value_vn="hw"), [_attr("hw")], [], [], [], None)
    assert out is None
    rec = _ev(recs, "ask.change.pending_no_value")[-1]
    assert rec["context"]["reason_code"] == "PENDING_REPLY_TOPIC_SWITCH"
    _no_sentinel(recs)


def test_rule_consistency_issue_attrs_only(recs, monkeypatch):
    monkeypatch.setattr(ask_api, "_cpq_engine", _Eng(
        apply_hiding_rules=lambda *a, **k: (None, None, set()),
        payload_flow_exclusions=lambda *a: set(),
        find_rule_inconsistencies=lambda *a, **k: [
            {"attr": "colorVn", "value": SENTINEL, "rule_type": "constraint", "issue": SENTINEL}],
        array_grid_controls_in_play=lambda a: []))
    _mod("ask_step2_rule_consistency")._step2_log_rule_consistency_and_array_grid(
        _req(), _session(), [], [], [], [], None, "cat")
    rec = _ev(recs, "ask.preamble.rule_consistency")[-1]
    assert rec["context"]["reason_code"] == "RULE_INCONSISTENCIES"
    assert rec["context"]["issue_attrs"] == ["colorVn"]
    _no_sentinel(recs)


# ------------------------------------------------------------------ steps 6-8

def test_review_routing_not_review(recs):
    out = _mod("ask_step678_review_status")._handle_review_status_routing(
        _req(), _session(status="configuring"), [], None, {}, [], [], [], None, "cat")
    assert out is None
    assert _ev(recs, "ask.review.routing")[-1]["context"]["reason_code"] == "STATUS_NOT_REVIEW"
    _no_sentinel(recs)


def test_review_json_preview(recs, monkeypatch):
    monkeypatch.setattr(ask_api, "_cpq_engine", _Eng(detect_response_mode_request=lambda q: "json"))
    m = _mod("ask_step678_json_and_approval")
    monkeypatch.setattr(m, "_build_json_preview_response", lambda *a, **k: {"answer": "x"})
    _mod("ask_step678_review_status")._handle_review_status_routing(
        _req(), _session(status="approved"), [], None, {}, [], [], [], None, "cat")
    assert _ev(recs, "ask.review.json_preview")[-1]["context"]["reason_code"] == "JSON_MODE_REQUESTED"
    stage = _ev(recs, "ask.review.routing stage")[-1]
    assert stage["level"] == "INFO" and stage["context"]["selected_option"] == "json_or_approval"
    assert _ev(recs, "ask.review.status legacy")
    _no_sentinel(recs)


def test_change_collision_reply_by_index(recs, monkeypatch):
    monkeypatch.setattr(ask_api, "_cpq_engine", _Eng(detect_change_request=lambda *a, **k: None,
                                                     next_question_prompt=lambda *a, **k: ""))
    m = _mod("ask_step678_change_collision")
    monkeypatch.setattr(m, "_queue_followup_note", lambda *a: "")
    s = _session(pending_change_collision_vns=["a1", "a2"],
                 pending_change_collision_question=f"change it {SENTINEL}")
    out = m._resolve_pending_change_collision(_req("2"), s, [_attr("a1"), _attr("a2")], [], [], [])
    assert out is not None
    rec = _ev(recs, "ask.collision.change_reply resolution")[-1]
    assert rec["context"]["selected_option"] == "list_index"
    assert rec["context"]["resolved_variable_name"] == "a2"
    assert _ev(recs, "ask.collision.change_reply resolved")[-1]["context"]["selected_option"] == "ask_value"
    _no_sentinel(recs)


def test_options_collision_unrecognized(recs, monkeypatch):
    monkeypatch.setattr(ask_api, "_cpq_engine", _Eng())
    m = _mod("ask_step678_options_collision")
    monkeypatch.setattr(m._ask_decline_reply_and_label_collision_llm_module,
                        "_llm_resolve_label_collision", lambda *a: None)
    s = _session(pending_label_collision_vns=["a1", "a2"])
    assert m._resolve_pending_options_collision(
        _req(), s, [_attr("a1"), _attr("a2")], None, "cat", [], [], [], None) is None
    assert _ev(recs, "ask.collision.options_reply resolution")[-1]["context"]["selected_option"] == "llm_no_match"
    assert _ev(recs, "ask.collision.options_reply stale")[-1]["context"]["reason_code"] == "REPLY_UNRECOGNIZED"
    _no_sentinel(recs)


def test_change_collision_detect(recs, monkeypatch):
    monkeypatch.setattr(ask_api, "_cpq_engine", _Eng(detect_change_request_collision=lambda *a, **k: [
        _attr("a1", label="Color"), _attr("a2", label="Color")]))
    m = _mod("ask_step678_change_collision_detect")
    monkeypatch.setattr(m, "_scan_and_enqueue_remaining_targets", lambda *a, **k: None)
    monkeypatch.setattr(m, "_queue_followup_note", lambda *a: "")
    assert m._step6_change_collision_detect(_req(), _session(), []) is not None
    rec = _ev(recs, "ask.collision.change_detect")[-1]
    assert rec["context"]["candidate_vns"] == ["a1", "a2"]
    _no_sentinel(recs)


def test_change_dispatch_llm_rejected(recs, monkeypatch):
    monkeypatch.setattr(ask_api, "_cpq_engine", _Eng(
        detect_change_requests_multi=lambda *a, **k: [],
        detect_change_request=lambda *a, **k: (_attr("hw"), SENTINEL)))
    m = _mod("ask_step678_change_dispatch")
    monkeypatch.setattr(m._ask_shadow_classify_and_confirm_intent_module,
                        "_llm_confirm_deterministic_intent", lambda *a, **k: False)
    assert m._step6_change_dispatch(_req(), _session(), [], [], [], [], None, "cat") is None
    rec = _ev(recs, "ask.change.dispatch")[-1]
    assert rec["context"]["selected_option"] == "llm_rejected"
    assert rec["context"]["variable_name"] == "hw"
    _no_sentinel(recs)


def test_activation_and_bulk(recs, monkeypatch):
    monkeypatch.setattr(ask_api, "_cpq_engine", _Eng(
        detect_attr_activation=lambda *a, **k: _attr("acc"),
        detect_bulk_quantity_change=lambda *a: ("mount", ["r1", "r2"], 67)))
    act = _mod("ask_step678_activation_and_clear")
    monkeypatch.setattr(act._ask_shadow_classify_and_confirm_intent_module,
                        "_llm_confirm_deterministic_intent", lambda *a, **k: True)
    monkeypatch.setattr(act._ask_handle_attr_activation_module, "_handle_attr_activation",
                        lambda *a, **k: {"answer": "x"})
    act._step6_activation_and_clear(_req(), _session(), [], [], [], [], None, "cat")
    assert _ev(recs, "ask.change.activation")[-1]["context"]["reason_code"] == "ACTIVATION_CONFIRMED"
    bulk = _mod("ask_step678_bulk_and_removal")
    monkeypatch.setattr(bulk, "_handle_bulk_quantity_change", lambda *a, **k: {"answer": "x"})
    bulk._step6_bulk_and_removal(_req(), _session(), [], [], [], [], None, "cat")
    rec = _ev(recs, "ask.change.bulk_quantity")[-1]
    assert rec["context"]["row_count"] == 2 and rec["context"]["new_quantity"] == 67
    _no_sentinel(recs)


def test_llm_fallback_change_no_value(recs, monkeypatch):
    m = _mod("ask_step678_llm_fallback")
    monkeypatch.setattr(m._ask_llm_classify_change_intent_module, "_llm_classify_change_intent",
                        lambda *a: ({"intent": "change", "variable_name": "hw", "value": ""}, 5, 7))
    monkeypatch.setattr(m, "_build_no_value_response", lambda *a, **k: {"answer": "x"})
    monkeypatch.setattr(m, "_with_classify_usage", lambda r, *a: r)
    m._step6_llm_fallback_classify(_req(), _session(), [_attr("hw")], [], [], [], None)
    rec = _ev(recs, "ask.change.llm_fallback")[-1]
    assert rec["context"]["selected_option"] == "ask_value"
    assert rec["context"]["reason_code"] == "LLM_CHANGE_NO_VALUE"
    _no_sentinel(recs)


def test_llm_fallback_value_text_never_logged(recs, monkeypatch):
    m = _mod("ask_step678_llm_fallback")
    monkeypatch.setattr(m._ask_llm_classify_change_intent_module, "_llm_classify_change_intent",
                        lambda *a: ({"intent": "change", "variable_name": "hw", "value": SENTINEL}, 1, 1))
    monkeypatch.setattr(m._ask_handle_cascade_module, "_handle_cascade", lambda *a, **k: {"answer": "x"})
    monkeypatch.setattr(m, "_with_classify_usage", lambda r, *a: r)
    m._step6_llm_fallback_classify(_req(), _session(), [_attr("hw")], [], [], [], None)
    assert _ev(recs, "ask.change.llm_fallback")[-1]["context"]["selected_option"] == "cascade"
    _no_sentinel(recs)


def test_nudge(recs, monkeypatch):
    monkeypatch.setattr(ask_api, "_cpq_engine", _Eng(rule_governed_ids=lambda *a: set()))
    m = _mod("ask_step678_no_value_and_nudge")
    monkeypatch.setattr(m, "_cpq_summary_text", lambda *a, **k: "")
    m._step6_no_value_or_nudge(_req(), _session(status="post_approval"), [], [], [], [], None)
    rec = _ev(recs, "ask.review.nudge")[-1]
    assert rec["level"] == "INFO" and rec["context"]["reason_code"] == "NO_DETECTOR_MATCHED"
    _no_sentinel(recs)
