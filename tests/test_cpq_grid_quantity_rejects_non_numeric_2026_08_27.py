"""Live-confirmed gap (2026-08-27): a grid-quantity question only ever
accepts a digit or a decline ("skip"/"none"/etc.) — parse_grid_quantity_
reply is the sole authority on that. Falling through to apply_answer() on
a parse miss (as every other optionless attr does) hit apply_answer's own
"Free-text field" tier (`if not attr.options and ...: return user_answer`),
which exists correctly for genuine free-text fields but silently accepted
"three" verbatim as this attr's QUANTITY:

    Q: mounting type Shirt Clip Mount Quantity — Please provide a value.
    A: three
    -> session.filled["mountingTypeShirtClipMountQuantity_viSoln"] = "three"
       filled_source = "user"  (never rejected, never re-asked)

Fix: a grid-quantity attr never falls through to apply_answer() at all —
a parse_grid_quantity_reply miss stays a miss, leaving the attribute
unfilled and still pending (re-asked), instead of accepting arbitrary
text as a number.
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _run_cpq_turn_inner
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attrs():
    multi_mount = ConfigAttr(
        entity_id=1, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi",
        options=_opt("Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount"),
    )
    shirt_qty = ConfigAttr(
        entity_id=2, variable_name="mountingTypeShirtMagneticMountQuantity_viSoln",
        display_label="mounting type Shirt Magnetic Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    clip_qty = ConfigAttr(
        entity_id=3, variable_name="mountingTypeShirtClipMountQuantity_viSoln",
        display_label="mounting type Shirt Clip Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    return [multi_mount, shirt_qty, clip_qty]


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


def test_unrecognized_word_is_rejected_not_stored_verbatim(monkeypatch):
    """The exact live-confirmed repro was "three" instead of "3" — since
    superseded by test_cpq_grid_quantity_natural_language_numbers_2026_08_27.py,
    which teaches the parser a small, fixed vocabulary of spelled-out
    numbers ("three" -> "3" is now correctly understood, not just safely
    rejected). This test keeps the underlying safety guarantee alive using
    a word genuinely outside that vocabulary, so a future vocabulary
    change can't silently regress the "never store verbatim" contract."""
    attrs = _attrs()
    _setup(monkeypatch, attrs)
    session = CpqSession(
        mode="cpq", product_name="Svx Video Remote Speaker Microphone",
        country="United States", status="configuring", turn=2,
        filled={}, filled_multi={},
        pending_variables=["mountingTypeShirtClipMountQuantity_viSoln"],
    )
    req = AskRequest(
        question="several", workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn_inner(req, object())
    session2 = CpqSession.from_dict(resp["session_data"])
    stored = session2.filled.get("mountingTypeShirtClipMountQuantity_viSoln")
    assert stored != "several", (
        "a non-numeric reply must never be stored verbatim as a quantity"
    )
    assert stored is None, "the attr must stay unfilled, not silently corrupted"
    assert "mountingTypeShirtClipMountQuantity_viSoln" in session2.pending_variables, (
        "an unrecognized reply must leave the question pending (re-asked), "
        "not silently drop it"
    )


def test_arbitrary_gibberish_is_also_rejected(monkeypatch):
    attrs = _attrs()
    _setup(monkeypatch, attrs)
    session = CpqSession(
        mode="cpq", product_name="Svx Video Remote Speaker Microphone",
        country="United States", status="configuring", turn=2,
        filled={}, filled_multi={},
        pending_variables=["mountingTypeShirtMagneticMountQuantity_viSoln"],
    )
    req = AskRequest(
        question="banana", workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn_inner(req, object())
    session2 = CpqSession.from_dict(resp["session_data"])
    assert session2.filled.get("mountingTypeShirtMagneticMountQuantity_viSoln") is None


def test_real_digit_reply_still_works_after_the_fix(monkeypatch):
    """Regression guard: the fix must not break the legitimate digit path."""
    attrs = _attrs()
    _setup(monkeypatch, attrs)
    session = CpqSession(
        mode="cpq", product_name="Svx Video Remote Speaker Microphone",
        country="United States", status="configuring", turn=2,
        filled={}, filled_multi={},
        pending_variables=["mountingTypeShirtClipMountQuantity_viSoln"],
    )
    req = AskRequest(
        question="3", workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn_inner(req, object())
    session2 = CpqSession.from_dict(resp["session_data"])
    assert session2.filled.get("mountingTypeShirtClipMountQuantity_viSoln") == "3"
    assert session2.filled_source.get("mountingTypeShirtClipMountQuantity_viSoln") == "user"


def test_decline_reply_still_works_after_the_fix(monkeypatch):
    """Regression guard: "skip" must still resolve to the literal "0"
    (the pre-existing, already-shipped 2026-08-26 behavior)."""
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
