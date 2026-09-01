"""Live-confirmed gap (2026-08-26, SVX Video Remote Speaker Microphone,
workspace 43): quoting the SVX and then typing the attribute's own name,
"Mounting Type (Array)", resolves the system-initiated label collision
onto mountingTypeArray_viSoln -- but the resolved question then showed the
raw 12-option "choose one" menu instead of the 2026-08-25 upfront
per-option-quantity flow (resolve_pending_grid_quantities/
append_pending_grid_quantities) that the normal auto-driven STEP-5
pending loop already gives this exact selector.

Root cause: TWO label-collision resolution call sites in ask_api.py both
asked the resolved attr's own next_question_prompt directly, never
routing it through append_pending_grid_quantities the way the normal
pending loop does:

  1. The awaiting-approval / options-query resolver (`if
     session.pending_label_collision_vns:` with a non-empty
     `_lc_orig_question` guard falling to the system-initiated branch
     below it).
  2. The actual mid-configuration path a live customer hits
     (`if session.pending_label_collision_vns and not session.
     pending_label_collision_question:`, checked before STEP 5's normal
     pending-answer handling) -- this is the one workspace 43's real
     conversation went through.

Fix: both call sites now call append_pending_grid_quantities on the
resolved attr before building its question; when it substitutes a real
linked quantity attr in place of the raw selector, ask THAT instead (and
queue any remaining per-option quantity attrs into
session.pending_variables) -- same substitution the normal pending loop
already performs, just applied at these resolution points too.
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _run_cpq_turn_inner
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


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


def _attrs():
    single_mount = ConfigAttr(
        entity_id=1, variable_name="mountType_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="single",
        options=_opt("Swivel Clip", "Adjustable Lanyard"),
    )
    multi_mount = ConfigAttr(
        entity_id=2, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi",
        options=_opt("Shirt Magnetic Mount", "Jacket Magnetic Mount", "Locking Molle Mount"),
    )
    shirt_qty = ConfigAttr(
        entity_id=3, variable_name="mountingTypeShirtMagneticMountQuantity_viSoln",
        display_label="mounting type Shirt Magnetic Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    jacket_qty = ConfigAttr(
        entity_id=4, variable_name="mountingTypeJacketMagneticMountQuantity_viSoln",
        display_label="mounting type Jacket Magnetic Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    locking_qty = ConfigAttr(
        entity_id=5, variable_name="mountingTypeLockingMolleMountQuantity_viSoln",
        display_label="mounting type Locking Molle Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    return [single_mount, multi_mount, shirt_qty, jacket_qty, locking_qty]


def _base_session(**overrides):
    kwargs = dict(
        mode="cpq", product_name="Svx Video Remote Speaker Microphone",
        country="United States", status="configuring", turn=2,
        filled={}, filled_multi={},
        pending_label_collision_vns=["mountType_viSoln", "mountingTypeArray_viSoln"],
        pending_label_collision_question="",
    )
    kwargs.update(overrides)
    return CpqSession(**kwargs)


def test_mid_config_collision_onto_unselected_grid_selector_asks_upfront_quantity(monkeypatch):
    """The actual path workspace 43's live conversation went through:
    status='configuring', mid-conversation, no original Q&A question."""
    attrs = _attrs()
    _setup(monkeypatch, attrs)
    session = _base_session()
    req = AskRequest(
        question="mountingTypeArray_viSoln", workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn_inner(req, object())
    answer = resp["answer"]

    assert "choose one" not in answer.lower(), (
        f"resolved a not-yet-selected grid selector to the raw choose-one menu "
        f"instead of the upfront per-option quantity flow: {answer!r}"
    )
    assert "Shirt Magnetic Mount Quantity" in answer, (
        f"expected the first linked option's quantity to be asked directly: {answer!r}"
    )

    session2 = CpqSession.from_dict(resp["session_data"])
    for qty_vn in (
        "mountingTypeShirtMagneticMountQuantity_viSoln",
        "mountingTypeJacketMagneticMountQuantity_viSoln",
        "mountingTypeLockingMolleMountQuantity_viSoln",
    ):
        assert qty_vn in session2.pending_variables, (
            f"{qty_vn!r} must be queued so every linked option's quantity gets "
            f"asked, not just the first: {session2.pending_variables!r}"
        )


def test_mid_config_collision_onto_already_selected_grid_selector_still_shows_choose_one(
    monkeypatch,
):
    """A selector the customer already answered directly (a real
    filled_multi entry) must NOT be routed through the upfront flow --
    that's upstream's grid-selector-multi-row re-ask territory (PR #277),
    untouched here."""
    attrs = _attrs()
    _setup(monkeypatch, attrs)
    session = _base_session(
        turn=3, filled_multi={"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]},
    )
    req = AskRequest(
        question="mountingTypeArray_viSoln", workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn_inner(req, object())
    answer = resp["answer"]

    assert "choose one" in answer.lower(), (
        f"an already-selected grid selector must keep upstream's re-ask "
        f"choose-one flow, not the upfront per-option flow: {answer!r}"
    )


def test_awaiting_approval_collision_onto_unselected_grid_selector_asks_upfront_quantity(
    monkeypatch,
):
    """The sibling options-query resolver (status='awaiting_approval')
    must get the same fix."""
    attrs = _attrs()
    _setup(monkeypatch, attrs)
    session = _base_session(status="awaiting_approval")
    req = AskRequest(
        question="mountingTypeArray_viSoln", workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn_inner(req, object())
    answer = resp["answer"]

    assert "choose one" not in answer.lower(), (
        f"resolved a not-yet-selected grid selector to the raw choose-one menu "
        f"instead of the upfront per-option quantity flow: {answer!r}"
    )
    assert "Shirt Magnetic Mount Quantity" in answer, (
        f"expected the first linked option's quantity to be asked directly: {answer!r}"
    )
