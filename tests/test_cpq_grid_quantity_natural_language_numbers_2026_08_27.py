"""Follow-up to test_cpq_grid_quantity_rejects_non_numeric_2026_08_27.py:
a customer plausibly types a spelled-out or "dozen"-family quantity
("three", "a dozen", "half a dozen", "2 dozen") instead of a bare digit.
Deliberately a small, FIXED vocabulary — never a general NLP number
parser — same "never guess, only convert a recognized phrasing"
discipline as the rest of this module. Negative quantities ("-5", "minus
6") are intentionally still rejected — a negative mount count has no
real business meaning.
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _run_cpq_turn_inner
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attrs():
    multi_mount = ConfigAttr(
        entity_id=1, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi",
        options=_opt("Shirt Magnetic Mount", "Jacket Magnetic Mount"),
    )
    shirt_qty = ConfigAttr(
        entity_id=2, variable_name="mountingTypeShirtMagneticMountQuantity_viSoln",
        display_label="mounting type Shirt Magnetic Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    return [multi_mount, shirt_qty]


def _setup(monkeypatch, attrs):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules",
        lambda *a, **k: ([], []),
    )
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda *a, **k: (attrs, "Svx Video Remote Speaker Microphone"),
    )


class TestParseGridQuantityReplyWordForms:
    """Direct unit coverage of the parser itself."""

    def test_spelled_out_number_resolves(self):
        assert CpqEngine().parse_grid_quantity_reply("three") == "3"

    def test_spelled_out_number_is_case_insensitive(self):
        assert CpqEngine().parse_grid_quantity_reply("Three") == "3"
        assert CpqEngine().parse_grid_quantity_reply("TWELVE") == "12"

    def test_zero_word_resolves(self):
        assert CpqEngine().parse_grid_quantity_reply("zero") == "0"

    def test_dozen_resolves_to_12(self):
        assert CpqEngine().parse_grid_quantity_reply("dozen") == "12"
        assert CpqEngine().parse_grid_quantity_reply("a dozen") == "12"

    def test_half_a_dozen_resolves_to_6(self):
        assert CpqEngine().parse_grid_quantity_reply("half a dozen") == "6"
        assert CpqEngine().parse_grid_quantity_reply("half dozen") == "6"

    def test_digit_n_dozen_resolves(self):
        assert CpqEngine().parse_grid_quantity_reply("2 dozen") == "24"

    def test_word_n_dozen_resolves(self):
        assert CpqEngine().parse_grid_quantity_reply("three dozen") == "36"

    def test_negative_digit_is_still_rejected(self):
        assert CpqEngine().parse_grid_quantity_reply("-5") is None

    def test_minus_word_is_still_rejected(self):
        assert CpqEngine().parse_grid_quantity_reply("minus 6") is None

    def test_unrecognized_word_is_still_rejected(self):
        assert CpqEngine().parse_grid_quantity_reply("banana") is None

    def test_word_number_beyond_the_fixed_vocabulary_is_rejected(self):
        # Deliberately a small, fixed vocabulary (zero..twenty) -- never a
        # general NLP parser. "thirty" is out of scope, not a guess.
        assert CpqEngine().parse_grid_quantity_reply("thirty") is None


def test_spelled_out_number_reply_stores_the_digit_end_to_end(monkeypatch):
    """The exact original repro, now resolving correctly instead of just
    being safely rejected: "three" -> stored as "3", not re-asked."""
    attrs = _attrs()
    _setup(monkeypatch, attrs)
    session = CpqSession(
        mode="cpq", product_name="Svx Video Remote Speaker Microphone",
        country="United States", status="configuring", turn=2,
        filled={}, filled_multi={},
        pending_variables=["mountingTypeShirtMagneticMountQuantity_viSoln"],
    )
    req = AskRequest(
        question="three", workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn_inner(req, object())
    session2 = CpqSession.from_dict(resp["session_data"])
    assert session2.filled.get("mountingTypeShirtMagneticMountQuantity_viSoln") == "3"
    assert session2.filled_source.get("mountingTypeShirtMagneticMountQuantity_viSoln") == "user"
    assert "mountingTypeShirtMagneticMountQuantity_viSoln" not in session2.pending_variables


def test_dozen_reply_stores_12_end_to_end(monkeypatch):
    attrs = _attrs()
    _setup(monkeypatch, attrs)
    session = CpqSession(
        mode="cpq", product_name="Svx Video Remote Speaker Microphone",
        country="United States", status="configuring", turn=2,
        filled={}, filled_multi={},
        pending_variables=["mountingTypeShirtMagneticMountQuantity_viSoln"],
    )
    req = AskRequest(
        question="a dozen", workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn_inner(req, object())
    session2 = CpqSession.from_dict(resp["session_data"])
    assert session2.filled.get("mountingTypeShirtMagneticMountQuantity_viSoln") == "12"


def test_negative_quantity_reply_still_rejected_end_to_end(monkeypatch):
    """Regression guard: negative quantities stay rejected (correct
    behavior, not a gap) -- the attribute stays pending."""
    attrs = _attrs()
    _setup(monkeypatch, attrs)
    session = CpqSession(
        mode="cpq", product_name="Svx Video Remote Speaker Microphone",
        country="United States", status="configuring", turn=2,
        filled={}, filled_multi={},
        pending_variables=["mountingTypeShirtMagneticMountQuantity_viSoln"],
    )
    req = AskRequest(
        question="minus 6", workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn_inner(req, object())
    session2 = CpqSession.from_dict(resp["session_data"])
    assert session2.filled.get("mountingTypeShirtMagneticMountQuantity_viSoln") is None
    assert "mountingTypeShirtMagneticMountQuantity_viSoln" in session2.pending_variables
