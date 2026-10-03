"""Raven structured-log placements for the ask request/route/turn flow (area ``ask_turn``, R1-R6, R8-R10, R12, G9)."""
from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aryx import raven_log as rl

SENTINEL = "SENTINEL-CUSTOMER-TEXT-9917"

_MODULES = [
    "aryx.api.ask_run_ask",
    "aryx.api.ask_run_ask_router_error",
    "aryx.api.ask_thread_api",
    "aryx.api.ask_thread_helpers",
    "aryx.api.security",
    "aryx.api.ask_standard_pipeline._pipeline",
    "aryx.api.ask_qa.ask_qa_graph_search",
    "aryx.api.ask_country_change_revalidate",
    "aryx.api.ask_turn_dispatch",
    "aryx.api.ask_core_helpers",
    "aryx.cpq.bom_gate.bom_gate",
    "aryx.cpq.intent_queue.intent_queue",
    "aryx.cpq.session_guard.session_guard_invariant",
    "aryx.cpq.intent_gateway.intent_gateway",
]


@pytest.fixture
def recs(monkeypatch):
    """Capture every record emitted by the ask-turn modules (all levels)."""
    out: list[dict] = []

    def fake(level, criticality, message, **kw):
        out.append({"level": level, "crit": criticality, "message": message,
                    "error_code": kw.get("error_code", ""), "context": kw.get("context") or {},
                    "trace_id": rl.current_run_id()})
        return {}

    for name in _MODULES:
        mod = importlib.import_module(name)
        monkeypatch.setattr(mod, "raven_log", fake)
    rl.bind_run_id("run-turn-1")
    yield out
    rl.bind_run_id("")


def _ev(recs, event):
    return [r for r in recs if r["message"].startswith(event)]


def _no_sentinel(recs):
    assert SENTINEL not in json.dumps(recs, default=str)


# ---------------------------------------------------------------- R1 R2 R3

def _client():
    from aryx.api.ask_thread_api import ask_thread_router
    from aryx.api.security import require_api_key

    app = FastAPI()
    app.include_router(ask_thread_router())
    app.dependency_overrides[require_api_key] = lambda: "k"
    return TestClient(app, raise_server_exceptions=False)


class _Store:
    def __init__(self, fail_assistant=False, fail_prompt=False):
        self.fail_assistant, self.fail_prompt = fail_assistant, fail_prompt

    def close(self): ...
    def validate_mapping(self, *a): ...
    def get_completed_response(self, *a): return None
    def conversation_history(self, *a, **k): return []
    def mark_request_completed(self, *a): ...
    def mark_request_retryable(self, *a): ...

    def ensure_thread_and_user_message(self, **k):
        if self.fail_prompt:
            raise RuntimeError("db down")
        return {"channel_id": "c1", "request_claimed": True}

    def append_assistant_message(self, **k):
        if self.fail_assistant:
            raise RuntimeError("db down")
        return {"citations": []}


_BODY = {"workspace_id": 7, "shay_workspace_id": "s", "thread_id": "t1", "request_id": "r1",
         "question": SENTINEL}


def _post(monkeypatch, store, run_ask):
    monkeypatch.setattr("aryx.api.ask_thread_api._store", lambda: store)
    monkeypatch.setattr("aryx.api.ask_thread_api._validate_workspace", lambda w: None)
    monkeypatch.setattr("aryx.api.ask_thread_api.run_ask", run_ask)
    return _client().post("/ask/threads/message", json=_BODY)


def test_turn_completed_has_ids_road_and_persisted(recs, monkeypatch):
    from aryx.api import ask_run_ask

    def ok(req):
        ask_run_ask._last_road.set("quote")
        return {"answer": "hi", "session_data": {"status": "configuring", "run_id": "run-turn-1"}}

    assert _post(monkeypatch, _Store(), ok).status_code == 200
    (r,) = _ev(recs, "ask.turn.completed")
    assert r["level"] == "INFO"
    c = r["context"]
    assert c["reason_code"] == "quote" and c["final_status"] == "configuring"
    assert (c["thread_id"], c["request_id"], c["workspace_id"]) == ("t1", "r1", 7)
    assert c["persisted"] is True and c["run_id"] == "run-turn-1"
    assert r["trace_id"] == "run-turn-1"
    _no_sentinel(recs)


def test_turn_completed_persisted_false_and_persist_failed_warn(recs, monkeypatch):
    _post(monkeypatch, _Store(fail_assistant=True), lambda req: {"answer": "x"})
    (pf,) = _ev(recs, "ask.persist.failed")
    assert pf["level"] == "WARN" and pf["error_code"] == "ARYX_ASK_PERSIST_FAILED"
    assert pf["context"]["operation"] == "save_response"
    (done,) = _ev(recs, "ask.turn.completed")
    assert done["context"]["persisted"] is False


def test_prompt_persist_failed(recs, monkeypatch):
    resp = _post(monkeypatch, _Store(fail_prompt=True), lambda req: {})
    assert resp.status_code == 503
    (pf,) = _ev(recs, "ask.persist.failed")
    assert pf["context"]["operation"] == "save_prompt" and pf["context"]["error_class"] == "RuntimeError"


def test_turn_failed_error_with_class_and_last_step(recs, monkeypatch):
    from aryx.api import ask_run_ask

    def boom(req):
        ask_run_ask.note_step("step9_lock_pending_answer")
        raise ValueError(SENTINEL)

    resp = _post(monkeypatch, _Store(), boom)
    assert resp.status_code == 502
    (r,) = _ev(recs, "ask.turn.failed")
    assert r["level"] == "ERROR" and r["crit"] == "P2" and r["error_code"] == "ARYX_ASK_RUN_FAILED"
    assert r["context"]["reason_code"] == "ValueError"
    assert r["context"]["last_step"] == "step9_lock_pending_answer"
    _no_sentinel(recs)


def test_helpers_release_and_complete_failures(recs):
    from aryx.api.ask_thread_helpers import (
        _complete_request_after_success, _release_failed_request_after_persist_error)

    class Bad:
        def mark_request_retryable(self, *a): raise RuntimeError("x")
        def mark_request_completed(self, *a): raise RuntimeError("x")

    assert _release_failed_request_after_persist_error(Bad(), "t", "r")
    assert _complete_request_after_success(Bad(), "t", "r")
    ops = [r["context"]["operation"] for r in _ev(recs, "ask.persist.failed")]
    assert ops == ["release", "complete"]


# ---------------------------------------------------------------- R4

def _run_ask_env(monkeypatch, mode="shadow", session_data=None, question="hello"):
    from aryx.api import ask_api, ask_run_ask

    calls = []
    monkeypatch.setattr(ask_run_ask._ask_core_helpers_module, "_reader", lambda w: object())
    monkeypatch.setattr(ask_api, "get_settings", lambda: SimpleNamespace(
        cpq_intent_mode=mode, cpq_intent_timeout_s=5))
    monkeypatch.setattr(ask_run_ask, "_route_quote", lambda *a, **k: calls.append("quote") or {})
    monkeypatch.setattr(
        ask_run_ask._ask_standard_pipeline_module, "_standard_ask_pipeline",
        lambda *a, **k: calls.append("standard") or {})
    req = SimpleNamespace(question=question, workspace_id=1, history=[],
                          session_data=session_data or {})
    return ask_run_ask, req, calls


def test_route_selected_live_session(recs, monkeypatch):
    mod, req, calls = _run_ask_env(monkeypatch, session_data={"product_name": "P"})
    mod.run_ask(req)
    (r,) = _ev(recs, "ask.route.selected")
    c = r["context"]
    assert c["selected_option"] == "quote" and c["reason_code"] == "LIVE_SESSION"
    assert c["policy_version"] == "shadow" and "standard" in c["available_options"]
    assert mod.current_road() == "quote"


def test_route_selected_hard_off_topic_and_check_trail(recs, monkeypatch):
    from aryx.api import ask_api
    mod, req, calls = _run_ask_env(monkeypatch)
    monkeypatch.setattr(ask_api, "hard_off_topic", lambda q: True)
    mod.run_ask(req)
    assert calls == ["standard"]
    assert _ev(recs, "ask.route.check live_session")
    (r,) = _ev(recs, "ask.route.selected")
    assert r["context"]["reason_code"] == "HARD_OFF_TOPIC" and r["context"]["selected_option"] == "standard"


def test_route_selected_llm_first_route_and_classified_trail(recs, monkeypatch):
    from aryx.api import ask_api, ask_run_ask
    mod, req, calls = _run_ask_env(monkeypatch, mode="llm_first")
    monkeypatch.setattr(ask_api, "hard_off_topic", lambda q: False)
    monkeypatch.setattr(ask_api, "detect_feature_region_search", lambda q: ("", "", ""))
    monkeypatch.setattr(ask_api, "soft_quote_heuristic", lambda q: False)
    monkeypatch.setattr(ask_api, "mark_top_level_route_used", lambda: None)
    monkeypatch.setattr(ask_run_ask._ask_finish_cpq_result_module, "_deterministic_cpq_gate",
                        lambda r, rd: True)
    meta = SimpleNamespace(route="quote", confidence="high", agreement=True, error=None,
                           timed_out=False, model_id="m", rationale="r")
    monkeypatch.setattr(ask_api, "classify_ask_route", lambda *a, **k: meta)
    mod.run_ask(req)
    assert calls == ["quote"]
    assert _ev(recs, "ask.route.classified")[0]["context"]["confidence"] == "high"
    (r,) = _ev(recs, "ask.route.selected")
    assert r["context"]["reason_code"] == "LLM_ROUTE" and r["context"]["llm_route"] == "quote"


# ---------------------------------------------------------------- R5

def _meta(timed_out=False):
    return SimpleNamespace(error="boom", timed_out=timed_out, prompt_tokens=0,
                           completion_tokens=0, model_id="m")


def test_router_failed_llm_first_error(recs, monkeypatch):
    from aryx.api import ask_api
    from aryx.api.ask_run_ask_router_error import _handle_router_error
    monkeypatch.setattr(ask_api, "logger", SimpleNamespace(
        warning=lambda *a, **k: None, error=lambda *a, **k: None, info=lambda *a, **k: None))
    out = _handle_router_error(SimpleNamespace(session_data={}), object(), _meta(True),
                               "llm_first", False, False)
    assert "Something went wrong" in out["answer"]
    (r,) = _ev(recs, "ask.router.failed_surfaced")
    assert r["level"] == "ERROR" and r["error_code"] == "ARYX_ASK_ROUTER_FAILED"
    assert r["context"]["recovery_selected"] == "customer_error" and r["context"]["timed_out"] is True


def test_router_failed_shadow_fallback(recs, monkeypatch):
    from aryx.api import ask_api, ask_run_ask_router_error as mod
    monkeypatch.setattr(ask_api, "logger", SimpleNamespace(
        warning=lambda *a, **k: None, error=lambda *a, **k: None, info=lambda *a, **k: None))
    monkeypatch.setattr(mod, "_route_quote", lambda *a, **k: {})
    mod._handle_router_error(SimpleNamespace(session_data={}), object(), _meta(), "shadow", True, False)
    (r,) = _ev(recs, "ask.router.failed_surfaced")
    assert r["level"] == "WARN" and r["context"]["recovery_selected"] == "deterministic_fallback"
    assert _ev(recs, "ask.route.selected")[0]["context"]["reason_code"] == "ESCAPE_HATCH"


# ---------------------------------------------------------------- R6

def test_standard_pipeline_degraded(recs, monkeypatch):
    from aryx.api.ask_standard_pipeline import _pipeline as p
    monkeypatch.setattr(p, "all_types", lambda r: [])
    monkeypatch.setattr(p, "build_overview", lambda r, w: "")
    monkeypatch.setattr(p, "_extract_terms", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(SENTINEL)))
    out = p._standard_ask_pipeline(SimpleNamespace(question="q", history=[], workspace_id=1), object())
    assert out["answer"].startswith("LLM unavailable")
    (r,) = _ev(recs, "ask.answer.degraded")
    assert r["level"] == "ERROR" and r["error_code"] == "ARYX_ASK_ANSWER_DEGRADED"
    assert r["context"]["dependency_name"] == "oci_genai" and r["context"]["result"] == "error_answer_returned"
    _no_sentinel([{**r, "message": r["message"]}] and [{"c": r["context"]}])


def test_qa_graph_search_degraded(recs, monkeypatch):
    from aryx.api import ask_api
    from aryx.api.ask_qa.ask_qa_graph_search import _qa_graph_search
    monkeypatch.setattr(ask_api, "all_types", lambda r: [])
    monkeypatch.setattr(ask_api, "logger", SimpleNamespace(warning=lambda *a, **k: None))
    monkeypatch.setattr(
        "aryx.api.ask_qa.ask_qa_graph_search._ask_standard_pipeline_module._extract_terms",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    ans, _ = _qa_graph_search(SimpleNamespace(question="q", history=[], workspace_id=1),
                              SimpleNamespace(run_id="r"), [], object(), None, 0, 0)
    assert ans.startswith("Couldn't reach the graph")
    (r,) = _ev(recs, "ask.answer.degraded")
    assert r["context"]["dependency_name"] == "graph" and r["error_code"] == "ARYX_ASK_ANSWER_DEGRADED"


# ---------------------------------------------------------------- R8

def _attr(vn, required=True):
    return SimpleNamespace(variable_name=vn, display_label=vn, required=required)


def test_bom_gate_decisions(recs, monkeypatch):
    from aryx.cpq.bom_gate import bom_gate as g
    session = SimpleNamespace(run_id="r", filled={"a": "1"}, filled_multi={}, product_name="Prod")
    # missing required
    monkeypatch.setattr(g, "find_missing_required_fields", lambda a, s: [_attr("country")])
    assert not g.validate_before_payload(None, [], session, [], None).ok
    r = _ev(recs, "ask.bom_gate.decision")[-1]
    assert r["level"] == "WARN" and r["error_code"] == "ARYX_ASK_BOM_MISSING_REQUIRED"
    assert r["context"]["missing_fields"] == ["country"] and r["context"]["policy_version"] == "bom_gate_v1"
    # recheck failed
    monkeypatch.setattr(g, "find_missing_required_fields", lambda a, s: [])
    monkeypatch.setattr(g, "recheck_constraints", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    g.validate_before_payload(None, [], session, [], None)
    assert _ev(recs, "ask.bom_gate.decision")[-1]["error_code"] == "ARYX_ASK_BOM_RECHECK_FAILED"
    # hard fail
    monkeypatch.setattr(g, "recheck_constraints", lambda *a: [])
    monkeypatch.setattr(g, "check_provenance", lambda a, s: ["bad value"])
    g.validate_before_payload(None, [], session, [], None)
    assert _ev(recs, "ask.bom_gate.decision")[-1]["error_code"] == "ARYX_ASK_BOM_HARD_FAIL"
    # pass
    monkeypatch.setattr(g, "check_provenance", lambda a, s: [])
    assert g.validate_before_payload(None, [], session, [], None).ok
    r = _ev(recs, "ask.bom_gate.decision")[-1]
    assert r["level"] == "INFO" and r["context"]["decision"] == "pass" and r["context"]["resource"] == "Prod"


# ---------------------------------------------------------------- R9

def test_intent_dropped(recs):
    from aryx.cpq.intent_queue.intent_queue import audit_intent_conservation
    res = audit_intent_conservation(SENTINEL, ["a", "b"], ["a"], {"run_id": "r", "turn": 2})
    assert res.dropped == ["b"]
    (r,) = _ev(recs, "ask.intent.dropped")
    assert r["level"] == "WARN" and r["error_code"] == "ARYX_ASK_INTENT_DROPPED"
    assert r["context"]["dropped_fields"] == ["b"]
    _no_sentinel(recs)
    recs.clear()
    audit_intent_conservation("q", ["a"], ["a"], {"run_id": "r"})
    assert _ev(recs, "ask.intent.conserved") and not _ev(recs, "ask.intent.dropped")


# ---------------------------------------------------------------- R10

def test_auth_store_failure_and_allow_deny_never_log_key(recs, monkeypatch):
    from aryx.api import security
    monkeypatch.setenv("ARYX_INTERNAL_API_KEY", "x" * 20)
    assert security._verify_key("x" * 20)
    allow = _ev(recs, "auth.api_key.check")[-1]
    assert allow["level"] == "DEBUG" and allow["context"]["decision"] == "allow"
    recs.clear()
    monkeypatch.setenv("ARYX_INTERNAL_API_KEY", "")
    monkeypatch.setattr("aryx.config.get_settings",
                        lambda: (_ for _ in ()).throw(RuntimeError("token store down")))
    secret = "very-secret-key-123456"
    assert security._verify_key(secret) is False
    (r,) = _ev(recs, "auth.api_key.check_failed")
    assert r["level"] == "ERROR" and r["crit"] == "P1" and r["error_code"] == "ARYX_AUTH_STORE_FAILED"
    assert r["context"]["decision"] == "deny" and r["context"]["reason_code"] == "TOKEN_STORE_ERROR"
    assert secret not in json.dumps(recs, default=str)


# ---------------------------------------------------------------- R12

def test_orphan_question_no_answer_text(recs):
    from aryx.cpq.session_guard.session_guard_invariant import assert_conversational_invariant
    answer = f"{SENTINEL} Which country would you like?"
    assert assert_conversational_invariant(answer, {}, run_id="r")
    (r,) = _ev(recs, "ask.invariant.orphan_question")
    assert r["level"] == "WARN" and r["error_code"] == "ARYX_ASK_ORPHAN_QUESTION"
    assert r["context"]["answer_len"] == len(answer)
    _no_sentinel(recs)
    recs.clear()
    assert not assert_conversational_invariant("Done.", {})
    assert _ev(recs, "ask.invariant.checked")[0]["context"]["reason_code"] == "NOT_CONFIG_QUESTION"


def test_country_rederive_failed(recs, monkeypatch):
    from aryx.api import ask_api
    from aryx.api.ask_country_change_revalidate import _rederive_and_revalidate_for_country_change
    engine = SimpleNamespace(load_product_config=lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(ask_api, "_cpq_engine", engine)
    monkeypatch.setattr(ask_api, "logger", SimpleNamespace(warning=lambda *a, **k: None,
                                                          info=lambda *a, **k: None))
    session = SimpleNamespace(product_name="P", turn=3, run_id="r")
    _rederive_and_revalidate_for_country_change(SimpleNamespace(workspace_id=1), session, "Canada", object())
    (r,) = _ev(recs, "ask.country_rederive.failed")
    assert r["level"] == "WARN" and r["error_code"] == "ARYX_ASK_COUNTRY_REDERIVE_FAILED"
    assert r["context"]["recovery_selected"] == "skip_revalidation"


# ---------------------------------------------------------------- gateway + G9

def test_classify_intent_wrapper_logs_action_and_ran_and_did_nothing(recs, monkeypatch):
    from aryx.cpq.intent_gateway import intent_gateway as ig
    dec = ig.GatewayDecision(action="fallback", result=None, reason="timeout", model_id="m")
    monkeypatch.setattr(ig, "_classify_intent_inner", lambda *a, **k: dec)
    assert ig.classify_intent(SENTINEL, [], None, None) is dec
    (r,) = _ev(recs, "ask.intent.gateway")
    c = r["context"]
    assert c["selected_option"] == "fallback" and c["reason_code"] == "timeout"
    assert c["ran_and_did_nothing"] is True and c["question_len"] == len(SENTINEL)
    _no_sentinel(recs)


def test_gateway_pool_worker_keeps_trace_id(recs, monkeypatch):
    """G9: the route-classification pool worker sees the caller's bound run id."""
    from aryx.cpq.intent_gateway import intent_gateway as ig
    seen = []
    monkeypatch.setattr(ig, "_pinned_chat", lambda *a, **k: (seen.append(rl.current_run_id()) or "{}", 0, 0))
    monkeypatch.setattr(ig, "get_settings", lambda: SimpleNamespace(
        cpq_intent_gemini_model="m", cpq_intent_timeout_s=5))
    try:
        ig.classify_ask_route("q", workspace_id=1, session_hint="x", det_is_cpq=False, timeout_s=5.0)
    except Exception:
        pass
    assert seen and seen[0] == "run-turn-1"
