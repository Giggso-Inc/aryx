"""Raven structured-log placements for product switch, preamble gates and model-leaf resolution."""
from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest

import aryx.api.ask_api as ask_api
from aryx.api import ask_core_helpers
from aryx.cpq.state import CpqSession

SENTINEL = "SENTINEL-CUSTOMER-TEXT-4471"

_MODULES = [
    "aryx.api.ask_turn_switch.ask_turn_confirm_switch_anchor",
    "aryx.api.ask_turn_switch.ask_turn_confirm_switch_decline",
    "aryx.api.ask_turn_switch.ask_turn_intent_diagnostics",
    "aryx.api.ask_turn_switch.ask_turn_product_switch_complete",
    "aryx.api.ask_turn_switch.ask_turn_seed_product_anchor",
    "aryx.api.ask_turn_switch.ask_turn_suggest_switch_anchor",
    "aryx.api.ask_turn_switch.ask_turn_switch_answer_guard",
    "aryx.api.ask_turn_switch.ask_turn_switch_country_anchor",
    "aryx.api.ask_turn_switch.ask_turn_switch_redetect_prompt",
    "aryx.api.ask_preamble.ask_preamble_country_change",
    "aryx.api.ask_preamble.ask_preamble_quantity_background",
    "aryx.api.ask_preamble.ask_preamble_quantity_gate",
    "aryx.api.ask_preamble.ask_preamble_quantity_target_resolve",
    "aryx.api.ask_model_leaf.ask_model_leaf_ask_prompt",
    "aryx.api.ask_model_leaf.ask_model_leaf_pending_reply",
    "aryx.cpq.nl_hint_extraction.model_leaves",
]


def _mod(name):
    return importlib.import_module(name)


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
            monkeypatch.setattr(mod, "would_log", lambda _lv: True)
    monkeypatch.setattr(ask_core_helpers, "_persist_cpq_history", lambda *a, **k: None)
    yield out


def _ev(recs, event):
    return [r for r in recs if r["message"].startswith(event)]


def _no_sentinel(recs):
    assert recs
    assert SENTINEL not in json.dumps(recs, default=str)


def _req(text):
    return SimpleNamespace(question=text, workspace_id=1)


def _session(**kw):
    s = CpqSession()
    s.product_name = kw.pop("product_name", "prodA_BOM")
    s.turn = 3
    for k, v in kw.items():
        setattr(s, k, v)
    return s


class _Engine:
    def __init__(self, detect=None, suggestions=(), intents_raise=False):
        self._detect, self._sugg, self._raise = detect, list(suggestions), intents_raise

    def ingested_product_alias_map(self, *a, **k): return {}
    def detect_product_mention(self, *a, **k): return self._detect
    def suggest_product_candidates(self, *a, **k): return list(self._sugg)
    def apply_answer(self, *a, **k): return None

    def count_turn_intents(self, *a, **k):
        if self._raise:
            raise RuntimeError("boom")
        return ["attr_change"]


# ------------------------------------------------------------- switch gates

def test_confirm_switch_clear_decline_logs_stay_and_declined(recs, monkeypatch):
    from aryx.api.ask_turn_switch.ask_turn_confirm_switch_anchor import _handle_confirm_switch_anchor
    monkeypatch.setattr(ask_api, "_cpq_engine", _Engine(detect=None))
    s = _session(pending_switch_product="prodB_BOM", pending_anchor="confirm_switch")
    out = _handle_confirm_switch_anchor(_req(f"no {SENTINEL}"), s, None, {})
    assert out["tools_called"] == ["cpq_switch_declined()"]
    cls = _ev(recs, "ask.switch.confirm_reply")[0]
    assert cls["level"] == "DEBUG"
    assert cls["context"]["selected_option"] == "stay"
    assert cls["context"]["reason_code"] == "CLEAR_DECLINE"
    dec = _ev(recs, "ask.switch.declined")[0]
    assert dec["level"] == "INFO" and dec["context"]["reason_code"] == "NO_PRODUCT_REDETECTED"
    _no_sentinel(recs)


def test_confirm_switch_yes_completes_switch(recs, monkeypatch):
    from aryx.api.ask_turn_switch import ask_turn_confirm_switch_anchor as m
    monkeypatch.setattr(ask_api, "_cpq_engine", _Engine())
    s = _session(pending_switch_product="prodB_BOM", pending_anchor="confirm_switch", country="")
    assert m._handle_confirm_switch_anchor(_req(f"yes {SENTINEL}"), s, None, {}) is None
    assert _ev(recs, "ask.switch.confirm_reply")[0]["context"]["reason_code"] == "DETERMINISTIC_AFFIRMATIVE"
    assert _ev(recs, "ask.switch.confirm_country")[0]["context"]["selected_option"] == "complete_switch"
    done = _ev(recs, "ask.switch.completed")[0]
    assert done["level"] == "INFO"
    assert done["context"]["reason_code"] == "NO_PRIOR_SNAPSHOT"
    assert done["context"]["to_product"] == "prodB_BOM"
    _no_sentinel(recs)


def test_decline_naming_other_product_reoffers(recs, monkeypatch):
    from aryx.api.ask_turn_switch.ask_turn_confirm_switch_decline import _handle_confirm_switch_decline
    monkeypatch.setattr(ask_api, "_cpq_engine", _Engine(detect="prodC_BOM"))
    s = _session(pending_switch_product="prodB_BOM")
    _handle_confirm_switch_decline(_req(SENTINEL), s, None, {})
    r = _ev(recs, "ask.switch.reoffer")[0]
    assert r["level"] == "INFO" and r["context"]["reason_code"] == "REDETECTED_DIFFERENT_PRODUCT"
    _no_sentinel(recs)


def test_suggest_switch_bare_yes_reprompts(recs):
    from aryx.api.ask_turn_switch.ask_turn_suggest_switch_anchor import _handle_suggest_switch_anchor
    s = _session(pending_switch_candidates=["x_BOM", "y_BOM"], pending_anchor="suggest_switch")
    _handle_suggest_switch_anchor(_req(f"yes {SENTINEL}"), s)
    r = _ev(recs, "ask.switch.suggest_reply")[0]
    assert r["level"] == "INFO"
    assert r["context"]["selected_option"] == "reprompt_candidates"
    assert r["context"]["reason_code"] == "BARE_YES_MULTIPLE_CANDIDATES"
    _no_sentinel(recs)


def test_switch_country_still_invalid_reasks_without_country_text(recs, monkeypatch):
    from aryx.api.ask_turn_switch import ask_turn_switch_country_anchor as m
    monkeypatch.setattr(m, "_country_available_for", lambda *a: False)
    s = _session(pending_switch_product="prodB_BOM", pending_anchor="switch_country")
    m._handle_switch_country_anchor(_req(SENTINEL), s, None)
    r = _ev(recs, "ask.switch.country_reask")[0]
    assert r["level"] == "INFO" and r["context"]["reason_code"] == "COUNTRY_NOT_AVAILABLE_FOR_NEW_PRODUCT"
    assert r["context"]["country_len"] == len(SENTINEL)
    _no_sentinel(recs)


def test_answer_guard_and_redetect_suggestions(recs, monkeypatch):
    from aryx.api.ask_turn_switch.ask_turn_switch_redetect import _check_mid_turn_switch_redetection
    monkeypatch.setattr(ask_api, "_cpq_engine", _Engine(detect=None, suggestions=["x_BOM", "y_BOM"]))
    s = _session()
    out = _check_mid_turn_switch_redetection(_req(SENTINEL), s, None, [], {})
    assert out["tools_called"] == ["cpq_switch_ambiguous()"]
    g = _ev(recs, "ask.switch.answer_guard")[0]
    assert g["context"]["selected_option"] == "probe_switch"
    assert g["context"]["reason_code"] == "NO_PENDING_ATTR"
    r = _ev(recs, "ask.switch.redetect")[0]
    assert r["level"] == "INFO" and r["context"]["reason_code"] == "MULTIPLE_SUGGESTIONS"
    _no_sentinel(recs)


def test_redetect_no_candidate_debug(recs, monkeypatch):
    from aryx.api.ask_turn_switch.ask_turn_switch_redetect_prompt import _build_switch_redetect_prompt
    monkeypatch.setattr(ask_api, "_cpq_engine", _Engine())
    assert _build_switch_redetect_prompt(_req(SENTINEL), _session(), None, {}, None, None) is None
    r = _ev(recs, "ask.switch.redetect")[0]
    assert r["level"] == "DEBUG" and r["context"]["reason_code"] == "NO_CANDIDATE_NO_SUGGESTIONS"
    _no_sentinel(recs)


def test_intent_diagnostic_failure_warns(recs, monkeypatch):
    from aryx.api.ask_turn_switch.ask_turn_intent_diagnostics import _log_turn_intent_diagnostics
    monkeypatch.setattr(ask_api, "_cpq_engine", _Engine(intents_raise=True))
    monkeypatch.setattr(ask_api, "get_settings", lambda: SimpleNamespace(cpq_shadow_intent_enabled=False))
    _log_turn_intent_diagnostics(_req(SENTINEL), _session(), [])
    w = _ev(recs, "ask.intent.count_failed")[0]
    assert w["level"] == "WARN" and w["error_code"] == "ARYX_ASK_INTENT_COUNT_FAILED"
    assert w["context"]["triggering_error"] == "RuntimeError"
    assert _ev(recs, "ask.intent.shadow_gate")[0]["context"]["reason_code"] == "SHADOW_INTENT_DISABLED"
    _no_sentinel(recs)


# ------------------------------------------------------------- preamble gates

def test_country_change_skip_and_llm_failed(recs, monkeypatch):
    m = _mod("aryx.api.ask_preamble.ask_preamble_country_change")
    monkeypatch.setattr(m, "detect_country_change_request", lambda q: None)
    assert m._preamble_country_change_gate(_req(SENTINEL), _session(), None) is None
    assert _ev(recs, "ask.preamble.country_change")[0]["context"]["reason_code"] == "NO_CHANGE_REQUEST"
    monkeypatch.setattr(m, "detect_country_change_request", lambda q: "x")
    monkeypatch.setattr(m, "_llm_confirm_and_extract_country", lambda *a, **k: (False, None, True))
    monkeypatch.setattr(m, "_build_llm_call_failed_response", lambda *a: {"answer": "failed"})
    m._preamble_country_change_gate(_req(SENTINEL), _session(), None)
    e = [r for r in recs if r["level"] == "ERROR"][0]
    assert e["error_code"] == "ARYX_ASK_COUNTRY_CHANGE_LLM_FAILED"
    assert e["context"]["reason_code"] == "LLM_CALL_FAILED"
    _no_sentinel(recs)


def test_quantity_background_direct_capture(recs, monkeypatch):
    m = _mod("aryx.api.ask_preamble.ask_preamble_quantity_background")
    monkeypatch.setattr(m, "extract_quantity_hint", lambda q: 7)
    monkeypatch.setattr(m, "is_valid_product_quantity", lambda v: True)
    monkeypatch.setattr(m, "quantity_turn_precheck", lambda q, a: None)
    s = _session()
    assert m._preamble_capture_quantity_background(_req(SENTINEL), s, None) == 7
    r = _ev(recs, "ask.preamble.quantity_background")[0]
    assert r["context"]["selected_option"] == "set_direct" and r["context"]["reason_code"] == "NO_CHANGE_VERB"
    _no_sentinel(recs)


def test_quantity_gate_skip_and_target_no_candidates(recs):
    from aryx.api.ask_preamble.ask_preamble_quantity_gate import _preamble_dedicated_quantity_gate
    from aryx.api.ask_preamble.ask_preamble_quantity_target_resolve import _preamble_resolve_quantity_target
    assert _preamble_dedicated_quantity_gate(_req(SENTINEL), _session(product_name=""), None) is None
    assert _ev(recs, "ask.preamble.quantity_gate")[0]["context"]["reason_code"] == "NO_PRODUCT_SELECTED"
    tgt, _c = _preamble_resolve_quantity_target(_req(SENTINEL), _session(), {"candidates": []})
    assert tgt == "product"
    r = _ev(recs, "ask.preamble.quantity_target")[0]
    assert r["context"]["reason_code"] == "NO_FILLED_CANDIDATE" and r["context"]["llm_consulted"] is False
    _no_sentinel(recs)


# ------------------------------------------------------------- model leaf

def test_model_leaf_pending_reply_picked(recs, monkeypatch):
    m = _mod("aryx.api.ask_model_leaf.ask_model_leaf_pending_reply")
    monkeypatch.setattr(m, "_resolve_scope_reply", lambda *a, **k: SimpleNamespace(matched="leafA_BOM"))
    s = _session(pending_model_leaf_candidates=["leafA_BOM", "leafB_BOM"])
    leaf, early = m._resolve_pending_model_leaf_reply(_req(SENTINEL), s)
    assert leaf == "leafA_BOM" and early is None
    r = _ev(recs, "ask.model_leaf.pending_reply")[0]
    assert r["level"] == "DEBUG" and r["context"]["reason_code"] == "CANDIDATE_MATCHED"
    assert r["context"]["picked_leaf"] == "leafA_BOM"
    _no_sentinel(recs)


class _LeafReader:
    def __init__(self, ents): self._ents = ents
    def find_entities(self, **k): return self._ents


class _LeafEngine:
    def __init__(self, props): self._props = props
    def _batch_fetch(self, ids, ws): return self._props


def test_model_variable_candidates_and_single(recs):
    from aryx.cpq.nl_hint_extraction.model_leaves import model_variable_candidates, single_model_variable_name
    ents = [{"id": 1, "name": "fam"}, {"id": 2, "name": "a"}, {"id": 3, "name": "b"}]
    props = {1: {"id": "10", "parent_id": "-1", "name": "fam_BOM"},
             2: {"id": "11", "parent_id": "10", "name": "a_BOM"},
             3: {"id": "12", "parent_id": "10", "name": "b_BOM"}}
    assert model_variable_candidates(_LeafEngine(props), _LeafReader(ents), 1, "Px") == ["a_BOM", "b_BOM"]
    c = _ev(recs, "ask.model_leaf.candidates")[0]
    assert c["context"]["reason_code"] == "MULTIPLE_LEAVES" and c["context"]["leaf_count"] == 2
    assert single_model_variable_name(_LeafEngine(props), _LeafReader(ents), 1, "Px") == ""
    assert _ev(recs, "ask.model_leaf.single")[0]["context"]["reason_code"] == "MULTIPLE_LEAVES"
    assert single_model_variable_name(_LeafEngine(props), _LeafReader(ents), 1, "") == ""
    assert _ev(recs, "ask.model_leaf.single")[-1]["context"]["reason_code"] == "NO_CATALOG_PREFIX"
