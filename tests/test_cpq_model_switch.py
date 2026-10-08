"""Model switch inside one family (cpq_model_switch_snapshot_enabled).

Covers the offer inside `_handle_cascade`, the yes/no reply handler, and the
snapshot save/restore in `_complete_model_switch`: A -> B starts clean, B -> A
restores A, decline keeps everything, flag off keeps today's cascade.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import aryx.api.ask_api as api
from aryx.api import ask_core_helpers as _core
from aryx.api.ask_handle import ask_handle_cascade as cascade_mod
from aryx.api.ask_turn_switch import ask_turn_model_switch as ms
from aryx.api.ask_turn_switch import ask_turn_model_switch_complete as msc
from aryx.api.ask_turn_switch.ask_turn_product_switch_anchor import _handle_product_switch_pending_anchor
from aryx.cpq.catalog_profile import PRODUCT_LITERAL
from aryx.cpq.state import CpqSession

# Generic option table: wording -> (item_value, display_name).
_OPTIONS = {"model a": ("MODEL_A", "Model A"), "model b": ("MODEL_B", "Model B")}
_PRODUCT_ATTR = SimpleNamespace(variable_name=PRODUCT_LITERAL, select_type="single")


def _fake_apply_answer(_attr, text, *_a, **_k):
    """Match the option whose wording appears in the text."""
    low = (text or "").lower()
    return next((v for k, v in _OPTIONS.items() if k in low), None)


@pytest.fixture
def flag_on(monkeypatch):
    """Turn the flag on and stub the engine match and history writes."""
    monkeypatch.setattr(ms, "get_settings", lambda: SimpleNamespace(cpq_model_switch_snapshot_enabled=True))
    monkeypatch.setattr(api._cpq_engine, "apply_answer", _fake_apply_answer)
    monkeypatch.setattr(_core, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(ms, "_llm_classify_switch_reply", lambda *a, **k: "unclear")


def _session_on_model_a() -> CpqSession:
    """A session on Model A with one extra answer and a country."""
    return CpqSession(
        mode="cpq", product_name="FamilyX", country="United States", turn=4,
        status="awaiting_approval",
        filled={PRODUCT_LITERAL: "MODEL_A", "band": "VHF"},
        display_filled={PRODUCT_LITERAL: "Model A", "band": "VHF"},
        filled_source={PRODUCT_LITERAL: "user", "band": "user"},
    )


def _req(text: str):
    """A minimal ask request."""
    return SimpleNamespace(question=text, workspace_id=1)


def _offer(session: CpqSession, text: str):
    """Run the offer for a Product change worded as `text`."""
    return ms._offer_model_switch(_req(text), session, [], _PRODUCT_ATTR, text)


def test_product_change_offers_confirm_and_touches_no_answers(flag_on):
    s = _session_on_model_a()
    resp = _offer(s, "I want model b")
    assert resp is not None and "Switch to **Model B**" in resp["answer"]
    assert s.pending_anchor == ms.CONFIRM_MODEL_SWITCH_ANCHOR
    assert s.pending_model_switch == "MODEL_B"
    assert s.filled == {PRODUCT_LITERAL: "MODEL_A", "band": "VHF"}


def test_flag_off_runs_the_normal_cascade(monkeypatch):
    monkeypatch.setattr(ms, "get_settings", lambda: SimpleNamespace(cpq_model_switch_snapshot_enabled=False))
    assert _offer(_session_on_model_a(), "model b") is None


def test_change_of_another_answer_is_not_a_model_switch(flag_on):
    other = SimpleNamespace(variable_name="band", select_type="single")
    assert ms._offer_model_switch(_req("model b"), _session_on_model_a(), [], other, "model b") is None


def test_same_model_or_no_match_is_not_offered(flag_on):
    assert _offer(_session_on_model_a(), "model a") is None
    assert _offer(_session_on_model_a(), "something else") is None


def test_yes_switches_to_a_clean_slate_keeping_family_and_country(flag_on):
    s = _session_on_model_a()
    _offer(s, "model b")
    assert ms._handle_confirm_model_switch_anchor(_req("yes"), s) is None
    assert s.filled == {PRODUCT_LITERAL: "MODEL_B"}
    assert s.display_filled[PRODUCT_LITERAL] == "Model B"
    assert (s.product_name, s.country, s.status) == ("FamilyX", "United States", "configuring")
    assert s.pending_anchor == "" and s.pending_model_switch == ""
    assert s.model_snapshots["MODEL_A"]["filled"]["band"] == "VHF"


def test_clean_start_resets_the_product_entity_and_restore_brings_it_back(flag_on):
    s = _session_on_model_a()
    s.product_entity_id = 42
    _offer(s, "model b")
    ms._handle_confirm_model_switch_anchor(_req("yes"), s)
    assert s.product_entity_id == 0
    _offer(s, "model a")
    ms._handle_confirm_model_switch_anchor(_req("yes"), s)
    assert s.product_entity_id == 42


def test_restore_drops_base_model_so_it_rederives_for_the_current_country(flag_on):
    from aryx.cpq.catalog_profile import BASE_MODEL_LITERAL
    s = _session_on_model_a()
    s.filled[BASE_MODEL_LITERAL] = "BM_FOR_US"
    s.display_filled[BASE_MODEL_LITERAL] = "BM_FOR_US"
    _offer(s, "model b")
    ms._handle_confirm_model_switch_anchor(_req("yes"), s)
    s.country = "Canada"
    _offer(s, "model a")
    ms._handle_confirm_model_switch_anchor(_req("yes"), s)
    assert BASE_MODEL_LITERAL not in s.filled and BASE_MODEL_LITERAL not in s.display_filled
    assert s.filled["band"] == "VHF"


def test_switch_clears_a_pending_option_scope(flag_on):
    from aryx.cpq.pending_scope.pending_scope import set_pending_scope
    s = _session_on_model_a()
    set_pending_scope(s, kind="attr_options", candidates=["X"], origin_question="q", attr_vn="band", asked_turn=3)
    _offer(s, "model b")
    ms._handle_confirm_model_switch_anchor(_req("yes"), s)
    assert s.pending_scope_kind == ""


def test_decline_text_falls_back_to_the_item_value_without_a_display_name(flag_on):
    s = _session_on_model_a()
    s.display_filled.pop(PRODUCT_LITERAL)
    _offer(s, "model b")
    resp = ms._handle_confirm_model_switch_anchor(_req("no"), s)
    assert "stays on **MODEL_A**" in resp["answer"]


def test_switching_back_restores_the_first_model_answers(flag_on):
    s = _session_on_model_a()
    _offer(s, "model b")
    ms._handle_confirm_model_switch_anchor(_req("yes"), s)
    s.filled["band"] = "UHF"
    s.display_filled["band"] = "UHF"
    _offer(s, "back to model a")
    ms._handle_confirm_model_switch_anchor(_req("switch"), s)
    assert s.filled == {PRODUCT_LITERAL: "MODEL_A", "band": "VHF"}
    assert s.model_snapshots["MODEL_B"]["filled"]["band"] == "UHF"


def test_no_keeps_the_current_model_and_answers(flag_on):
    s = _session_on_model_a()
    _offer(s, "model b")
    resp = ms._handle_confirm_model_switch_anchor(_req("no thanks"), s)
    assert "stays on **Model A**" in resp["answer"]
    assert s.filled == {PRODUCT_LITERAL: "MODEL_A", "band": "VHF"}
    assert s.status == "awaiting_approval" and s.pending_anchor == ""
    assert s.model_snapshots == {}


def test_reply_naming_the_target_model_accepts(flag_on):
    s = _session_on_model_a()
    _offer(s, "model b")
    ms._handle_confirm_model_switch_anchor(_req("Model B"), s)
    assert s.filled[PRODUCT_LITERAL] == "MODEL_B"


def test_unclear_reply_uses_the_llm(flag_on, monkeypatch):
    monkeypatch.setattr(ms, "_llm_classify_switch_reply", lambda *a, **k: "accept")
    s = _session_on_model_a()
    _offer(s, "model b")
    ms._handle_confirm_model_switch_anchor(_req("sure, go ahead"), s)
    assert s.filled[PRODUCT_LITERAL] == "MODEL_B"


def test_pending_anchor_router_sends_the_reply_to_the_model_handler(flag_on):
    s = _session_on_model_a()
    _offer(s, "model b")
    assert _handle_product_switch_pending_anchor(_req("yes"), s, None, {}) is None
    assert s.filled[PRODUCT_LITERAL] == "MODEL_B"


def test_snapshot_cap_evicts_the_oldest_model():
    s = _session_on_model_a()
    for i in range(msc._MODEL_SNAPSHOT_CAP + 1):
        msc._complete_model_switch(s, f"M{i}", f"Model {i}")
    assert "MODEL_A" not in s.model_snapshots
    assert len(s.model_snapshots) == msc._MODEL_SNAPSHOT_CAP


def test_old_session_data_without_the_new_fields_loads():
    data = _session_on_model_a().to_dict()
    for key in ("model_snapshots", "pending_model_switch", "pending_model_switch_display"):
        data.pop(key)
    s = CpqSession.from_dict(data)
    assert s.model_snapshots == {} and s.pending_model_switch == ""


def test_snapshots_survive_the_session_data_round_trip(flag_on):
    s = _session_on_model_a()
    _offer(s, "model b")
    ms._handle_confirm_model_switch_anchor(_req("yes"), s)
    again = CpqSession.from_dict(s.to_dict())
    assert again.model_snapshots["MODEL_A"]["filled"]["band"] == "VHF"


def test_handle_cascade_returns_the_offer_before_wiping_anything(flag_on, monkeypatch):
    monkeypatch.setattr(cascade_mod, "_is_decline_reply", lambda *a, **k: False)
    monkeypatch.setattr(api._cpq_engine, "disambiguated_label", lambda *a, **k: "Product")

    def _must_not_run(*_a, **_k):
        raise AssertionError("cascade ran before the user confirmed")

    monkeypatch.setattr(cascade_mod, "_invalidate_cascade_dependents", _must_not_run)
    s = _session_on_model_a()
    resp = cascade_mod._handle_cascade(_req("model b"), s, [], _PRODUCT_ATTR, "model b", [], [], [])
    assert resp["tools_called"] == ["cpq_model_switch_candidate()"]
    assert s.filled["band"] == "VHF"
