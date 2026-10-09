"""Review-stage model switch from this turn's Product hint.

After "Configuration complete", a message naming a different Product option
("I want to quote for <model> ...") must ask the model-switch question before
the LLM-first gateway can turn it into an attribute-collision question.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import aryx.api.ask_api as api
from aryx.api import ask_core_helpers as _core
from aryx.api.ask_turn_steps import ask_step678_review_status as review
from aryx.api.ask_turn_switch import ask_turn_model_switch as ms
from aryx.api.ask_turn_switch import ask_turn_model_switch_hint as hint_mod
from aryx.cpq.catalog_profile import PRODUCT_LITERAL
from aryx.cpq.state import CpqSession

_PRODUCT_ATTR = SimpleNamespace(
    variable_name=PRODUCT_LITERAL, select_type="single",
    options=[SimpleNamespace(item_value="MODEL_A", display_name="Model A"),
             SimpleNamespace(item_value="MODEL_B", display_name="Model B")],
)


def _flag(on: bool):
    """Settings stub with only the model-switch flag."""
    return lambda: SimpleNamespace(cpq_model_switch_snapshot_enabled=on)


@pytest.fixture
def flag_on(monkeypatch):
    """Flag on, history writes stubbed."""
    monkeypatch.setattr(hint_mod, "get_settings", _flag(True))
    monkeypatch.setattr(_core, "_persist_cpq_history", lambda *a, **k: None)


def _session() -> CpqSession:
    """A completed quote on Model A."""
    return CpqSession(
        mode="cpq", product_name="FamilyX", country="United States", turn=6,
        status="awaiting_approval",
        filled={PRODUCT_LITERAL: "MODEL_A", "band": "VHF"},
        display_filled={PRODUCT_LITERAL: "Model A", "band": "VHF"},
        filled_source={PRODUCT_LITERAL: "user", "band": "user"},
    )


def _req(text: str = "I want to quote for Model B for United States"):
    """A minimal ask request."""
    return SimpleNamespace(question=text, workspace_id=1)


def test_hint_naming_another_model_asks_to_switch(flag_on):
    s = _session()
    resp = hint_mod._offer_model_switch_from_hint(_req(), s, [_PRODUCT_ATTR], {PRODUCT_LITERAL: "MODEL_B"})
    assert resp is not None and "Switch to **Model B**" in resp["answer"]
    assert s.pending_anchor == ms.CONFIRM_MODEL_SWITCH_ANCHOR and s.pending_model_switch == "MODEL_B"
    assert s.filled[PRODUCT_LITERAL] == "MODEL_A"


def test_flag_off_leaves_the_review_stage_alone(monkeypatch):
    monkeypatch.setattr(hint_mod, "get_settings", _flag(False))
    assert hint_mod._offer_model_switch_from_hint(
        _req(), _session(), [_PRODUCT_ATTR], {PRODUCT_LITERAL: "MODEL_B"}) is None


@pytest.mark.parametrize("hints", [{}, {PRODUCT_LITERAL: "MODEL_A"}, {PRODUCT_LITERAL: "NOT_AN_OPTION"}])
def test_no_hint_same_model_or_unknown_value_is_not_a_switch(flag_on, hints):
    s = _session()
    assert hint_mod._offer_model_switch_from_hint(_req(), s, [_PRODUCT_ATTR], hints) is None
    assert s.pending_anchor == ""


def test_hint_without_the_model_named_in_this_message_is_not_a_switch(flag_on):
    s = _session()
    assert hint_mod._offer_model_switch_from_hint(
        _req("change the band please"), s, [_PRODUCT_ATTR], {PRODUCT_LITERAL: "MODEL_B"}) is None
    assert s.pending_anchor == ""


@pytest.mark.parametrize("text", ["not Model B", "a quote without Model B", "I don't want Model B"])
def test_negated_model_mention_is_not_a_switch(flag_on, text):
    assert hint_mod._offer_model_switch_from_hint(
        _req(text), _session(), [_PRODUCT_ATTR], {PRODUCT_LITERAL: "MODEL_B"}) is None


def test_leading_no_far_from_the_model_still_offers(flag_on):
    resp = hint_mod._offer_model_switch_from_hint(
        _req("no ,i want a quote for Model B in the US"), _session(), [_PRODUCT_ATTR],
        {PRODUCT_LITERAL: "MODEL_B"})
    assert resp is not None


def test_other_hinted_changes_get_the_send_again_note(flag_on):
    band = SimpleNamespace(variable_name="band", select_type="single", options=[])
    resp = hint_mod._offer_model_switch_from_hint(
        _req("Model B with UHF"), _session(), [_PRODUCT_ATTR, band],
        {PRODUCT_LITERAL: "MODEL_B", "band": "UHF"})
    assert "not been applied yet" in resp["answer"]


def test_unchanged_other_hints_get_no_note(flag_on):
    band = SimpleNamespace(variable_name="band", select_type="single", options=[])
    resp = hint_mod._offer_model_switch_from_hint(
        _req(), _session(), [_PRODUCT_ATTR, band], {PRODUCT_LITERAL: "MODEL_B", "band": "VHF"})
    assert "not been applied yet" not in resp["answer"]


def test_other_hint_not_named_in_this_message_gets_no_note(flag_on):
    band = SimpleNamespace(variable_name="band", select_type="single", options=[])
    resp = hint_mod._offer_model_switch_from_hint(
        _req("I want Model B"), _session(), [_PRODUCT_ATTR, band],
        {PRODUCT_LITERAL: "MODEL_B", "band": "UHF"})
    assert "not been applied yet" not in resp["answer"]


def test_multi_select_product_is_not_a_switch(flag_on):
    multi = SimpleNamespace(**{**vars(_PRODUCT_ATTR), "select_type": "multi"})
    assert hint_mod._offer_model_switch_from_hint(
        _req(), _session(), [multi], {PRODUCT_LITERAL: "MODEL_B"}) is None


def test_name_scan_stays_fast_on_a_long_message():
    import time
    text = " ".join(f"word{i % 50}" for i in range(5000))
    t0 = time.perf_counter()
    assert hint_mod._name_start(text, ("Model B", "MODEL_B")) is None
    assert time.perf_counter() - t0 < 5.0  # the cubic version took 43 s on 2,000 words
    assert hint_mod._name_start(text + " model b", ("Model B",)) == 5000


def test_declined_switch_is_not_offered_again_so_the_gateway_can_run(flag_on, monkeypatch):
    monkeypatch.setattr(ms, "_llm_classify_switch_reply", lambda *a, **k: "unclear")
    s = _session()
    text = "set the DMS service to Model B"
    assert hint_mod._offer_model_switch_from_hint(_req(text), s, [_PRODUCT_ATTR], {PRODUCT_LITERAL: "MODEL_B"})
    assert ms._handle_confirm_model_switch_anchor(_req("no"), s) is not None
    assert s.declined_model_switch == ["MODEL_A", "MODEL_B"]
    assert hint_mod._offer_model_switch_from_hint(_req(text), s, [_PRODUCT_ATTR], {PRODUCT_LITERAL: "MODEL_B"}) is None


@pytest.mark.parametrize("text", [
    "ok, switch to Model B after all", "I want to quote for Model B", "let's go with Model B",
])
def test_explicit_switch_wording_offers_again_after_a_decline(flag_on, text):
    s = _session()
    s.declined_model_switch = ["MODEL_A", "MODEL_B"]
    assert hint_mod._offer_model_switch_from_hint(
        _req(text), s, [_PRODUCT_ATTR], {PRODUCT_LITERAL: "MODEL_B"}) is not None


@pytest.mark.parametrize("text", ["use Model A instead of Model B", "Model A rather than Model B"])
def test_instead_of_and_rather_than_negate_the_model_after_them(flag_on, text):
    assert hint_mod._offer_model_switch_from_hint(
        _req(text), _session(), [_PRODUCT_ATTR], {PRODUCT_LITERAL: "MODEL_B"}) is None


def test_decline_is_forgotten_after_an_accepted_switch(flag_on):
    s = _session()
    s.declined_model_switch = ["MODEL_A", "MODEL_X"]
    hint_mod._offer_model_switch_from_hint(_req(), s, [_PRODUCT_ATTR], {PRODUCT_LITERAL: "MODEL_B"})
    ms._handle_confirm_model_switch_anchor(_req("yes"), s)
    assert s.declined_model_switch == [] and s.filled[PRODUCT_LITERAL] == "MODEL_B"


def test_unclear_reply_is_not_recorded_as_a_decline(flag_on, monkeypatch):
    monkeypatch.setattr(ms, "_llm_classify_switch_reply", lambda *a, **k: "unclear")
    s = _session()
    hint_mod._offer_model_switch_from_hint(_req(), s, [_PRODUCT_ATTR], {PRODUCT_LITERAL: "MODEL_B"})
    assert ms._handle_confirm_model_switch_anchor(_req("what is the price difference?"), s) is None
    assert s.declined_model_switch == []
    assert hint_mod._offer_model_switch_from_hint(
        _req("ok, I want Model B"), s, [_PRODUCT_ATTR], {PRODUCT_LITERAL: "MODEL_B"}) is not None


@pytest.mark.parametrize("text,offers", [
    ("I don't really want Model B", False),
    ("not re-quote Model B", False),  # a hyphen no longer ends the clause
])
def test_negation_edge_cases(flag_on, text, offers):
    resp = hint_mod._offer_model_switch_from_hint(
        _req(text), _session(), [_PRODUCT_ATTR], {PRODUCT_LITERAL: "MODEL_B"})
    assert (resp is not None) is offers


def test_negation_about_the_old_model_still_offers(flag_on):
    resp = hint_mod._offer_model_switch_from_hint(
        _req("not Model A, Model B"), _session(), [_PRODUCT_ATTR], {PRODUCT_LITERAL: "MODEL_B"})
    assert resp is not None


def test_review_stage_asks_before_the_llm_gateway(flag_on, monkeypatch):
    for name in ("_step678_json_or_approval", "_resolve_pending_options_collision",
                 "_resolve_pending_change_collision"):
        monkeypatch.setattr(review, name, lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "detect_qa_question", lambda *a, **k: False)

    def _gateway_must_not_run(*_a, **_k):
        raise AssertionError("LLM gateway ran before the model-switch check")

    monkeypatch.setattr(review, "_llm_first_gateway_turn", _gateway_must_not_run)
    s = _session()
    resp = review._handle_review_status_routing(
        _req(), s, [_PRODUCT_ATTR], None, {PRODUCT_LITERAL: "MODEL_B"}, [], [], [], None, "")
    assert resp["tools_called"] == ["cpq_model_switch_candidate()"]


def test_yes_after_the_review_offer_switches_and_saves_the_old_model(flag_on, monkeypatch):
    monkeypatch.setattr(ms, "_llm_classify_switch_reply", lambda *a, **k: "unclear")
    s = _session()
    hint_mod._offer_model_switch_from_hint(_req(), s, [_PRODUCT_ATTR], {PRODUCT_LITERAL: "MODEL_B"})
    assert ms._handle_confirm_model_switch_anchor(_req("yes"), s) is None
    assert s.filled[PRODUCT_LITERAL] == "MODEL_B" and s.status == "configuring"
    assert s.model_snapshots["MODEL_A"]["filled"]["band"] == "VHF"
