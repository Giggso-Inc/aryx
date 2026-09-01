"""Explicit product decision (2026-08-26): when the upfront per-option
quantity flow asks for one grid-linked mount's quantity and the customer
replies "skip" (or any equivalent decline) or a bare "0", that option's
quantity attr must be recorded as the literal "0" and survive into the
final payload — a real, confirmed customer decision that this option
isn't wanted, not an unanswered gap silently dropped.

Root cause this closes: a free-text attr's generic answer-matching
(CpqEngine.apply_answer's "Free-text field" fallback) checks
`_valid(user_answer)` before accepting a reply verbatim. "0" is one of
`_NONE_VALUES` (`_valid("0")` is False), so a bare "0" reply fell through
as unrecognized and was never stored at all; a word like "skip" is NOT in
`_NONE_VALUES` (`_valid("skip")` is True), so it was accepted and stored
literally as the string "skip" — neither behavior is the "0" the payload
actually needs.

Fix: CpqEngine.parse_grid_quantity_reply (gated by is_grid_quantity_attr,
so this never touches an ordinary free-text field) is checked before the
generic apply_answer chain in ask_api.py's STEP-5 pending-answer handling
— "skip"/"none"/"no"/etc. and a bare "0" both resolve to the literal "0";
a whole number resolves to itself.
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
        options=_opt("Shirt Magnetic Mount", "Jacket Magnetic Mount", "Locking Molle Mount"),
    )
    shirt_qty = ConfigAttr(
        entity_id=2, variable_name="mountingTypeShirtMagneticMountQuantity_viSoln",
        display_label="mounting type Shirt Magnetic Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    jacket_qty = ConfigAttr(
        entity_id=3, variable_name="mountingTypeJacketMagneticMountQuantity_viSoln",
        display_label="mounting type Jacket Magnetic Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    locking_qty = ConfigAttr(
        entity_id=4, variable_name="mountingTypeLockingMolleMountQuantity_viSoln",
        display_label="mounting type Locking Molle Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    return [multi_mount, shirt_qty, jacket_qty, locking_qty]


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


class TestParseGridQuantityReply:
    """Direct unit coverage of the parser itself."""

    def test_skip_resolves_to_zero(self):
        assert CpqEngine().parse_grid_quantity_reply("skip") == "0"

    def test_none_needed_resolves_to_zero(self):
        assert CpqEngine().parse_grid_quantity_reply("not needed") == "0"

    def test_bare_zero_resolves_to_zero(self):
        assert CpqEngine().parse_grid_quantity_reply("0") == "0"

    def test_whole_number_resolves_to_itself(self):
        assert CpqEngine().parse_grid_quantity_reply("60") == "60"

    def test_gibberish_returns_none(self):
        assert CpqEngine().parse_grid_quantity_reply("banana") is None


def test_skip_reply_to_grid_quantity_question_stores_literal_zero(monkeypatch):
    attrs = _attrs()
    _setup(monkeypatch, attrs)
    session = CpqSession(
        mode="cpq", product_name="Svx Video Remote Speaker Microphone",
        country="United States", status="configuring", turn=2,
        filled={}, filled_multi={},
        pending_variables=["mountingTypeShirtMagneticMountQuantity_viSoln"],
    )
    req = AskRequest(
        question="skip", workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn_inner(req, object())
    session2 = CpqSession.from_dict(resp["session_data"])
    assert session2.filled.get("mountingTypeShirtMagneticMountQuantity_viSoln") == "0"
    assert session2.filled_source.get("mountingTypeShirtMagneticMountQuantity_viSoln") == "user"


def test_bare_zero_reply_to_grid_quantity_question_stores_literal_zero(monkeypatch):
    attrs = _attrs()
    _setup(monkeypatch, attrs)
    session = CpqSession(
        mode="cpq", product_name="Svx Video Remote Speaker Microphone",
        country="United States", status="configuring", turn=2,
        filled={}, filled_multi={},
        pending_variables=["mountingTypeJacketMagneticMountQuantity_viSoln"],
    )
    req = AskRequest(
        question="0", workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn_inner(req, object())
    session2 = CpqSession.from_dict(resp["session_data"])
    assert session2.filled.get("mountingTypeJacketMagneticMountQuantity_viSoln") == "0"


def test_zeroed_quantity_survives_into_final_payload(monkeypatch):
    attrs = _attrs()
    engine = CpqEngine()
    filled = {
        "mountingTypeShirtMagneticMountQuantity_viSoln": "0",
        "mountingTypeJacketMagneticMountQuantity_viSoln": "5",
    }
    filled_source = {
        "mountingTypeShirtMagneticMountQuantity_viSoln": "user",
        "mountingTypeJacketMagneticMountQuantity_viSoln": "user",
    }
    payload = engine.build_payload(filled, filled_source, {}, attrs)
    config_data = payload["configData"]
    assert config_data.get("mountingTypeShirtMagneticMountQuantity_viSoln") == "0", (
        f"a confirmed 0 quantity was dropped from the payload: {config_data!r}"
    )
    assert config_data.get("mountingTypeJacketMagneticMountQuantity_viSoln") == "5"


def test_whole_number_reply_still_stores_the_number(monkeypatch):
    attrs = _attrs()
    _setup(monkeypatch, attrs)
    session = CpqSession(
        mode="cpq", product_name="Svx Video Remote Speaker Microphone",
        country="United States", status="configuring", turn=2,
        filled={}, filled_multi={},
        pending_variables=["mountingTypeLockingMolleMountQuantity_viSoln"],
    )
    req = AskRequest(
        question="60", workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn_inner(req, object())
    session2 = CpqSession.from_dict(resp["session_data"])
    assert session2.filled.get("mountingTypeLockingMolleMountQuantity_viSoln") == "60"
