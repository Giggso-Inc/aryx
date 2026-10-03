"""Raven structured-log placements for the ask response builders and the Q&A road (area ``ask_response_qa``)."""
from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest

from aryx import raven_log as rl
from aryx.cpq.intent_schema.intent_schema import Confidence, IntentCategory

SENTINEL = "SENTINEL-CUSTOMER-TEXT-4471"

_RB = "aryx.api.ask_response_building."
_QA = "aryx.api.ask_qa."
_MODULES = [
    _RB + "ask_build_country_change_response", _RB + "ask_build_no_value_response",
    _RB + "ask_build_product_quantity_response", _RB + "ask_build_show_summary_response",
    _RB + "ask_cpq_summary_narrate", _RB + "ask_cpq_summary_text", _RB + "ask_mandatory_block_splice",
    _QA + "ask_qa_fast_path", _QA + "ask_qa_label_collision", _QA + "ask_qa_multi_attr_options",
    _QA + "ask_qa_resume_prompt", _QA + "ask_qa_status_shortcircuit",
]


@pytest.fixture
def recs(monkeypatch):
    """Capture every record emitted by the batch-B modules (all levels)."""
    out: list[dict] = []

    def fake(level, criticality, message, **kw):
        out.append({"level": level, "crit": criticality, "message": message,
                    "error_code": kw.get("error_code", ""), "context": kw.get("context") or {}})
        return {}

    for name in _MODULES:
        mod = importlib.import_module(name)
        monkeypatch.setattr(mod, "raven_log", fake)
        if hasattr(mod, "would_log"):
            monkeypatch.setattr(mod, "would_log", lambda lv: True)
    monkeypatch.setattr("aryx.api.ask_core_helpers._persist_cpq_history", lambda *a, **k: None)
    rl.bind_run_id("run-rqa-1")
    yield out
    rl.bind_run_id("")


def _ev(recs, event):
    return [r for r in recs if r["message"].startswith(event)]


def _no_sentinel(recs):
    assert recs, "expected at least one record"
    assert SENTINEL not in json.dumps(recs, default=str)


class _Sess(SimpleNamespace):
    def to_dict(self):
        return {}


def _session(**kw):
    base = dict(turn=4, run_id="run-rqa-1", country="US", filled={}, display_filled={},
                filled_source={}, filled_multi={}, pending_variables=[], product_name="APX",
                product_quantity=1, product_anchor_question=SENTINEL, pending_intent_queue=[],
                last_qa_variables=[])
    base.update(kw)
    return _Sess(**base)


def _req(q=f"what about {SENTINEL}"):
    return SimpleNamespace(question=q, workspace_id=7, history=[])


def _attr(vn, label="Band", options=()):
    return SimpleNamespace(variable_name=vn, display_label=label, entity_id=1, catalog_prefix="cat",
                           options=list(options))


def _engine(monkeypatch, **methods):
    eng = SimpleNamespace(_OPTIONS_KEYWORDS=("options", "available"), **methods)
    monkeypatch.setattr("aryx.api.ask_api._cpq_engine", eng)
    return eng


# ---------------------------------------------------------------- response builders

def test_country_change_noop_and_apply(recs, monkeypatch):
    from aryx.api.ask_response_building import ask_build_country_change_response as m
    monkeypatch.setattr(m, "_rederive_and_revalidate_for_country_change", lambda *a: None)
    m._build_country_change_response(_req(), _session(country="US"), "us")
    s = _session(filled={"modelSelectionRegion_astro": "NA", "color": "red"},
                 display_filled={"modelSelectionRegion_astro": "NA"})
    m._build_country_change_response(_req(), s, "Germany")
    noop = _ev(recs, "ask.response.country_change no-op")[0]
    assert noop["level"] == "DEBUG" and noop["context"]["reason_code"] == "COUNTRY_ALREADY_SET"
    applied = _ev(recs, "ask.response.country_change applied")[0]
    assert applied["level"] == "INFO" and applied["context"]["selected_option"] == "apply_change"
    assert applied["context"]["cleared_mirror_count"] == 1
    _no_sentinel(recs)


def test_no_value_response(recs, monkeypatch):
    from aryx.api.ask_response_building import ask_build_no_value_response as m
    monkeypatch.setattr(m, "_scan_and_enqueue_remaining_targets", lambda *a, **k: (["b"], []))
    monkeypatch.setattr(m, "clear_queue_vn", lambda *a: None)
    monkeypatch.setattr(m, "_queue_followup_note", lambda *a: "")
    monkeypatch.setattr(m, "_append_unmatched_targets_note", lambda r, *a: r)
    monkeypatch.setattr(m, "_apply_intent_conservation", lambda r, *a, **k: r)
    _engine(monkeypatch, apply_constraint_rules=lambda *a, **k: {},
            next_question_prompt=lambda *a, **k: "opts", disambiguated_label=lambda a, b: "Band")
    m._build_no_value_response(_req(), _session(filled={"band": "x"}), [_attr("band")],
                               _attr("band"), [], None, "cpq_change")
    r = _ev(recs, "ask.response.no_value")[0]
    assert r["level"] == "INFO" and r["context"]["reason_code"] == "CHANGE_TARGET_WITHOUT_VALUE"
    assert r["context"]["enqueued_count"] == 1 and r["context"]["answer_len"] > 0
    _no_sentinel(recs)


def test_product_quantity_branches(recs, monkeypatch):
    from aryx.api.ask_response_building import ask_build_product_quantity_response as m

    def boom(*a, **k):
        raise RuntimeError("db down")
    _engine(monkeypatch, load_product_config=boom)
    monkeypatch.setattr(m, "_build_show_summary_response", lambda *a: {"answer": "S", "tools_called": []})
    m._build_product_quantity_change_response(_req(), _session(), None, None, "10.0")
    m._build_product_quantity_change_response(_req(), _session(), None, -5)
    m._build_product_quantity_change_response(_req(), _session(), None, 3)
    m._build_product_quantity_change_response(_req(), _session(pending_variables=["band"]), None, 4)
    opts = [r["context"]["selected_option"] for r in _ev(recs, "ask.response.quantity_")]
    assert opts == ["reject_decimal", "reject_invalid", "summary", "plain", "plain"]
    warn = _ev(recs, "ask.response.quantity_resume_load_failed")[0]
    assert warn["level"] == "WARN" and warn["error_code"] == "ARYX_ASK_QTY_RESUME_LOAD_FAILED"
    assert warn["context"]["triggering_error"] == "RuntimeError"
    _no_sentinel(recs)


def test_show_summary_failure_and_complete(recs, monkeypatch):
    from aryx.api.ask_response_building import ask_build_show_summary_response as m

    def boom(*a, **k):
        raise ValueError("x")
    _engine(monkeypatch, load_product_config=boom)
    assert m._build_show_summary_response(_req(), _session(), None) is None
    _engine(monkeypatch, load_product_config=lambda *a: ([_attr("band")], "APX"),
            load_hiding_rules=lambda *a: [], load_recommendation_and_constraint_rules=lambda *a: ([], []),
            build_bml_evaluator=lambda *a: None, apply_hiding_rules=lambda *a, **k: (0, 0, set()),
            rule_governed_ids=lambda *a: {1})
    monkeypatch.setattr(m, "_cpq_summary_text", lambda *a, **k: "SUMMARY")
    m._build_show_summary_response(_req(), _session(display_filled={"band": "B"}), None)
    warn = _ev(recs, "ask.response.show_summary catalog load failed")[0]
    assert warn["level"] == "WARN" and warn["error_code"] == "ARYX_ASK_SHOW_SUMMARY_LOAD_FAILED"
    ok = _ev(recs, "ask.response.show_summary rendered")[0]
    assert ok["level"] == "INFO" and ok["context"]["reason_code"] == "CONFIG_COMPLETE"
    _no_sentinel(recs)


def _narrate(monkeypatch, chat, missing=((), ())):
    from aryx.api.ask_response_building import ask_cpq_summary_narrate as m
    seq = list(missing)
    monkeypatch.setattr(m.llm_runtime, "chat", chat)
    monkeypatch.setattr("aryx.cpq.summary_guard.fields_missing_from_summary",
                        lambda *a: list(seq.pop(0)) if seq else [])
    monkeypatch.setattr("aryx.cpq.summary_guard.raw_state_table", lambda *a: "RAW")
    _engine(monkeypatch, render_filled_summary=lambda *a, **k: "BULLETS")
    groups = [("Product Name", [("Model", "APX")])]
    return m._narrate_cpq_summary("sys", SENTINEL, 2, groups, 7, {"m": "APX"}, [], set(), None,
                                  None, set(), lambda t: t)


def test_narration_llm_accepted(recs, monkeypatch):
    out = _narrate(monkeypatch, lambda *a, **k: (f"Done. @@@ - {SENTINEL}", 5, 6))
    assert SENTINEL in out
    r = _ev(recs, "ask.response.summary_narrated")[0]
    assert r["level"] == "INFO" and r["context"]["selected_option"] == "llm_narration"
    _no_sentinel(recs)


def test_narration_fallbacks(recs, monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("llm")
    assert _narrate(monkeypatch, boom) == "BULLETS"
    assert _narrate(monkeypatch, lambda *a, **k: (SENTINEL, 1, 1)) == "BULLETS"
    assert _narrate(monkeypatch, lambda *a, **k: ("A. @@@ b", 1, 1), (["x=1"], [])) == "BULLETS"
    assert _narrate(monkeypatch, lambda *a, **k: ("A. @@@ b", 1, 1), (["x=1"], ["x=1"])) == "RAW"
    failed = _ev(recs, "ask.response.summary_failed")[0]
    assert failed["level"] == "WARN" and failed["error_code"] == "ARYX_ASK_SUMMARY_NARRATION_FAILED"
    assert failed["context"]["triggering_error"] == "TimeoutError"
    seg = _ev(recs, "ask.response.summary_segments")[0]
    assert seg["context"]["reason_code"] == "SEGMENT_COUNT_MISMATCH" and seg["level"] == "WARN"
    assert _ev(recs, "ask.response.summary_guard_miss")[0]["error_code"] == "ARYX_ASK_SUMMARY_GUARD_MISS"
    assert _ev(recs, "ask.response.summary_bullets")[0]["context"]["selected_option"] == "deterministic_bullets"
    raw = _ev(recs, "ask.response.summary_raw_table")[0]
    assert raw["level"] == "ERROR" and raw["context"]["selected_option"] == "raw_state_table"
    _no_sentinel(recs)


def test_summary_text_no_groups(recs, monkeypatch):
    from aryx.api.ask_response_building import ask_cpq_summary_text as m
    _engine(monkeypatch, load_layout_display_order=lambda *a: [], mandatory_tier_c_vns=lambda *a: set(),
            categorized_summary_groups=lambda *a, **k: [])
    assert m._cpq_summary_text({}, [], set(), "APX", 7) == ""
    assert _ev(recs, "ask.response.summary_skipped")[0]["context"]["reason_code"] == "NO_SUMMARY_GROUPS"


def test_mandatory_block_and_splice(recs):
    from aryx.api.ask_response_building import ask_mandatory_block_splice as m
    sec = m.CpqEngine._BEAUTIFY_MANDATORY_SECTION
    rows = [{"section": sec, "label": "Band", "value": SENTINEL}]
    assert m._beautify_mandatory_block(rows, {("band", SENTINEL.casefold())}) is None
    block = m._beautify_mandatory_block(rows, set())
    m._splice_mandatory_block_into_summary(f"{m._MANDATORY_HEADER}\nold", block)
    m._splice_mandatory_block_into_summary("x\n\nClick **JSON** below", block)
    m._splice_mandatory_block_into_summary("x", block)
    built = [r["context"]["selected_option"] for r in _ev(recs, "ask.response.mandatory_block")]
    assert built == ["none", "block"]
    spl = [r["context"]["selected_option"] for r in _ev(recs, "ask.response.mandatory_splice")]
    assert spl == ["replace_section", "insert_before_trailer", "append"]
    _no_sentinel(recs)


# ---------------------------------------------------------------- QA road

def test_fast_path_hit_miss_enumeration(recs, monkeypatch):
    from aryx.api.ask_qa import ask_qa_fast_path as m
    attrs = [_attr("band")]
    _engine(monkeypatch, detect_attr_query=lambda q, a: attrs[0] if "band" in q else None)
    monkeypatch.setattr(m, "_build_attr_options_text", lambda *a: f"opts {SENTINEL}")
    monkeypatch.setattr(m._ask_llm_catalog_enumeration_module, "_llm_detect_catalog_enumeration_query",
                        lambda *a: True)
    monkeypatch.setattr(m._ask_catalog_listing_text_module, "_build_catalog_attribute_listing_text",
                        lambda *a: SENTINEL)
    m._qa_fast_path_or_enumeration(_req(f"band {SENTINEL}"), _session(), attrs, "")
    assert m._qa_fast_path_or_enumeration(_req(f"hello {SENTINEL}"), _session(), attrs, "") is None
    m._qa_fast_path_or_enumeration(_req(f"list options {SENTINEL}"), _session(), attrs, "")
    opts = [(r["level"], r["context"]["selected_option"], r["context"]["reason_code"])
            for r in _ev(recs, "ask.qa.fast_path")]
    assert opts == [("INFO", "attr_options", "ATTR_QUERY_MATCHED"), ("DEBUG", "miss", "NO_OPTIONS_KEYWORD"),
                    ("INFO", "catalog_attribute_listing", "PRE_QUOTE_CATALOG")]
    _no_sentinel(recs)


def test_label_collision(recs, monkeypatch):
    from aryx.api.ask_qa import ask_qa_label_collision as m
    pair = [_attr("a_vn", "Band"), _attr("b_vn", "Band")]
    eng = _engine(monkeypatch, detect_label_collision=lambda q, a: [])
    monkeypatch.setattr(m, "_narrow_label_collision", lambda q, c: c)
    assert m._qa_label_collision_response(_req(), _session(), pair) is None
    eng.detect_label_collision = lambda q, a: pair
    m._qa_label_collision_response(_req(), _session(display_filled={"a_vn": SENTINEL}), pair)
    none, hit = _ev(recs, "ask.qa.label_collision")
    assert none["level"] == "DEBUG" and none["context"]["selected_option"] == "no_collision"
    assert hit["level"] == "INFO" and hit["context"]["reason_code"] == "SHARED_DISPLAY_LABEL"
    assert hit["context"]["candidate_vns"] == ["a_vn", "b_vn"]
    _no_sentinel(recs)


def test_multi_attr_options(recs, monkeypatch):
    from aryx.api.ask_qa import ask_qa_multi_attr_options as m
    attrs = [_attr("band"), _attr("carrier")]
    _engine(monkeypatch, detect_attr_query=lambda q, a: next((x for x in a if x.variable_name in q), None))
    monkeypatch.setattr(m, "_build_attr_options_text", lambda r, s, a, x: f"{x.variable_name} {SENTINEL}")
    monkeypatch.setattr(m._ask_llm_split_multi_attr_options_module, "_llm_split_multi_attr_options_query",
                        lambda *a: ["band", "carrier"])
    assert m._qa_multi_attr_options_response(_req(f"hi {SENTINEL}"), _session(), attrs) is None
    m._qa_multi_attr_options_response(_req(f"options band and carrier {SENTINEL}"), _session(), attrs)
    skip, hit = _ev(recs, "ask.qa.multi_attr_options")
    assert skip["context"]["reason_code"] == "NO_OPTIONS_KEYWORD_OR_CONJUNCTION"
    assert hit["level"] == "INFO" and hit["context"]["resolved_count"] == 2
    _no_sentinel(recs)


def test_resume_prompt(recs, monkeypatch):
    from aryx.api.ask_qa import ask_qa_resume_prompt as m
    _engine(monkeypatch, build_review_prompt=lambda *a: "R", next_question_prompt=lambda *a, **k: "Q")
    attrs = [_attr("band")]
    m._build_qa_resume_prompt(_session(), attrs, True)
    m._build_qa_resume_prompt(_session(pending_variables=["band"]), attrs, False)
    m._build_qa_resume_prompt(_session(), attrs, False)
    got = [r["context"]["selected_option"] for r in _ev(recs, "ask.qa.resume_prompt")]
    assert got == ["review", "resume_pending", "none"]


def test_status_shortcircuit(recs, monkeypatch):
    from aryx.api.ask_qa import ask_qa_status_shortcircuit as m
    _engine(monkeypatch, next_question_prompt=lambda *a, **k: "Q")
    meta = SimpleNamespace(category=IntentCategory.SESSION_STATUS_QUERY, confidence=Confidence.HIGH)
    monkeypatch.setattr(m._ask_llm_classify_intent_universal_module, "_llm_classify_intent_universal",
                        lambda *a: (meta, 3, 4))
    attrs = [_attr("band")]
    m._qa_status_shortcircuit(_req(), _session(), attrs, False)
    resp, *_ = m._qa_status_shortcircuit(_req(), _session(pending_variables=["band"]), attrs, False)
    assert resp is not None
    meta.confidence = Confidence.LOW
    m._qa_status_shortcircuit(_req(), _session(pending_variables=["band"]), attrs, False)
    got = [(r["context"]["selected_option"], r["context"]["reason_code"])
           for r in _ev(recs, "ask.qa.status_shortcircuit")]
    assert got == [("continue_qa", "NOTHING_PENDING"), ("short_circuit", "SESSION_STATUS_QUERY"),
                   ("continue_qa", "NOT_CONFIDENT_STATUS_QUERY")]
    _no_sentinel(recs)
