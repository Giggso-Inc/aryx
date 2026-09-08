"""End-to-end reproduction of the live-reported gap (2026-08-25, SVX
Video Remote Speaker Microphone): after replying "Shirt Magnetic Mount" to
the narrowed "Mounting Type (Array)" prompt and its quantity, the
configuration was declared COMPLETE -- the other 4 still-valid mounting
types (of the 5 the constraint narrows this model to) were never offered.

Drives the real turn handler (`_run_cpq_turn`), not engine internals
directly, to prove the fix reaches the customer-facing conversation.
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _run_cpq_turn
from aryx.cpq.bml import BmlEvaluator, clear_shared_bml_cache
from aryx.cpq.state import ConfigAttr, ConstraintRule, CpqSession, MenuOption
from aryx.api import ask_core_helpers as _ask_core_helpers_test_module

_VALID_FIVE = [
    "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount",
    "Jacket Clip Mount", "Locking Molle Mount",
]


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attrs():
    model_attr = ConfigAttr(
        entity_id=1, variable_name="modelSelectionSelectModel_viSoln",
        display_label="Select Model", required=False, default_value="",
        select_type="single", options=_opt("SVX Video Remote Speaker Mic TAA"),
    )
    multi_mount = ConfigAttr(
        entity_id=2, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi", options=_opt(*_VALID_FIVE),
    )
    qty_attrs = [
        ConfigAttr(
            entity_id=10 + i, variable_name=f"mountingType{n.replace(' ', '')}Quantity_viSoln",
            display_label=f"{n} Quantity", required=False, default_value="",
            select_type="single", options=[], hidden=True,
        )
        for i, n in enumerate(_VALID_FIVE)
    ]
    return [model_attr, multi_mount, *qty_attrs]


def _setup(monkeypatch, attrs, con_rules):
    monkeypatch.setattr(_ask_core_helpers_test_module, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules",
        lambda *a, **k: ([], con_rules),
    )
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda *a, **k: (attrs, "Svx Video Remote Speaker Microphone"),
    )


def setup_function(_fn):
    clear_shared_bml_cache()


def test_first_pick_of_five_is_still_offered_the_remaining_four(monkeypatch):
    attrs = _attrs()
    multi_mount = next(a for a in attrs if a.variable_name == "mountingTypeArray_viSoln")
    con_rule = ConstraintRule(
        rule_name="Constrain mounts for TAA",
        condition_attr_id=1, condition_value="SVX Video Remote Speaker Mic TAA",
        target_attr_id=multi_mount.entity_id, allowed_values=list(_VALID_FIVE),
    )
    _setup(monkeypatch, attrs, [con_rule])

    session = CpqSession(
        product_name="Svx Video Remote Speaker Microphone", country="United States",
        turn=3, filled={"modelSelectionSelectModel_viSoln": "SVX Video Remote Speaker Mic TAA"},
        filled_source={"modelSelectionSelectModel_viSoln": "user"},
        pending_variables=["mountingTypeArray_viSoln"],
    )

    # Turn 1: pick one of the five narrowed options.
    resp1 = _run_cpq_turn(
        AskRequest(question="Shirt Magnetic Mount", workspace_id=1, session_data=session.to_dict()),
        object(),
    )
    session2 = CpqSession.from_dict(resp1["session_data"])
    assert session2.filled_multi.get("mountingTypeArray_viSoln") == ["Shirt Magnetic Mount"]

    # Turn 2: answer its quantity follow-up.
    resp2 = _run_cpq_turn(
        AskRequest(question="60", workspace_id=1, session_data=resp1["session_data"]),
        object(),
    )

    # The customer must STILL be offered the other 4 valid mounting types —
    # not declared complete after only 1 of 5.
    answer2 = resp2["answer"]
    assert "Mounting Type" in answer2, (
        f"expected the grid selector to still be pending after 1 of 5 picks, "
        f"got: {answer2!r}"
    )
    for still_open in ("Jacket Magnetic Mount", "Shirt Clip Mount",
                       "Jacket Clip Mount", "Locking Molle Mount"):
        assert still_open in answer2, f"{still_open!r} must still be offered: {answer2!r}"
    # Already-picked option must NOT be re-listed as a numbered choice.
    assert "1. Shirt Magnetic Mount" not in answer2

    session3 = CpqSession.from_dict(resp2["session_data"])
    assert session3.filled_multi.get("mountingTypeArray_viSoln") == ["Shirt Magnetic Mount"], (
        "the first pick must survive into the second turn untouched"
    )


def test_declining_further_rows_settles_without_erasing_the_first_pick(monkeypatch):
    attrs = _attrs()
    multi_mount = next(a for a in attrs if a.variable_name == "mountingTypeArray_viSoln")
    con_rule = ConstraintRule(
        rule_name="Constrain mounts for TAA",
        condition_attr_id=1, condition_value="SVX Video Remote Speaker Mic TAA",
        target_attr_id=multi_mount.entity_id, allowed_values=list(_VALID_FIVE),
    )
    _setup(monkeypatch, attrs, [con_rule])

    session = CpqSession(
        product_name="Svx Video Remote Speaker Microphone", country="United States",
        turn=4, filled={"modelSelectionSelectModel_viSoln": "SVX Video Remote Speaker Mic TAA"},
        filled_source={"modelSelectionSelectModel_viSoln": "user",
                       "mountingTypeArray_viSoln": "user"},
        filled_multi={"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]},
        pending_variables=["mountingTypeArray_viSoln"],
    )

    resp = _run_cpq_turn(
        AskRequest(question="no more", workspace_id=1, session_data=session.to_dict()),
        object(),
    )

    session2 = CpqSession.from_dict(resp["session_data"])
    assert session2.filled_multi.get("mountingTypeArray_viSoln") == ["Shirt Magnetic Mount"], (
        "declining further rows must not erase the row already picked"
    )
    assert "mountingTypeArray_viSoln" in session2.pending_grid_declined_vns


def test_declining_drops_a_pick_a_later_constraint_has_since_invalidated(monkeypatch):
    """Raven review, PR #277 (medium): a pick preserved across turns must
    still be revalidated against the CURRENTLY active constraint set — a
    stale, now-illegal pick must never survive a decline into the payload.

    Simulates the state a mid-conversation constraint-narrowing change
    would produce (regionMode flips from US to EU, and the EU rule no
    longer allows "Shirt Magnetic Mount") directly on the session, then
    drives the decline turn against it — the mechanism under test (does
    decline revalidate?) doesn't depend on HOW the state became stale.
    """
    attrs = _attrs()
    multi_mount = next(a for a in attrs if a.variable_name == "mountingTypeArray_viSoln")
    region_attr = ConfigAttr(
        entity_id=3, variable_name="regionMode_astro", display_label="Region Mode",
        required=False, default_value="", select_type="single", options=_opt("US", "EU"),
    )
    attrs.append(region_attr)
    con_rule = ConstraintRule(
        rule_name="EU excludes Shirt Magnetic Mount",
        condition_attr_id=region_attr.entity_id, condition_value="EU",
        target_attr_id=multi_mount.entity_id,
        allowed_values=[v for v in _VALID_FIVE if v != "Shirt Magnetic Mount"],
    )
    _setup(monkeypatch, attrs, [con_rule])

    session = CpqSession(
        product_name="Svx Video Remote Speaker Microphone", country="United States",
        turn=5,
        filled={
            "modelSelectionSelectModel_viSoln": "SVX Video Remote Speaker Mic TAA",
            "regionMode_astro": "EU",
        },
        filled_source={
            "modelSelectionSelectModel_viSoln": "user", "regionMode_astro": "user",
            "mountingTypeArray_viSoln": "user",
        },
        # A pick made before regionMode flipped to EU -- now illegal under
        # the active constraint.
        filled_multi={"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]},
        pending_variables=["mountingTypeArray_viSoln"],
    )

    resp = _run_cpq_turn(
        AskRequest(question="no more", workspace_id=1, session_data=session.to_dict()),
        object(),
    )

    session2 = CpqSession.from_dict(resp["session_data"])
    assert session2.filled_multi.get("mountingTypeArray_viSoln") == [], (
        "the now-illegal pick must be dropped on decline, not shipped to the payload"
    )
