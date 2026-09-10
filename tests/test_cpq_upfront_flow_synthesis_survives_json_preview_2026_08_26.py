"""Live-confirmed incident (2026-08-26, SVX Video Remote Speaker
Microphone): a customer who answers every mount's quantity through the
upfront per-option flow (never directly answering the mountingTypeArray_
viSoln selector itself) sees "Configuration complete" and a correct
"Mandatory User Input" summary listing all 6 mounts — but asking "show me
the json" returns an EMPTY `configData`, silently dropping every mount's
quantity from the payload.

Root cause: `_finalize_grid_selections_from_quantities` synthesizes the
selector's `filled_multi` entry once every linked option's quantity is
answered, but never stamped a matching `filled_source` entry. The JSON
preview builds its payload with `scope_required_and_edited=True`, which
filters `configData` down to `_is_mandatory_input_attr`'s Tier A/B set —
requiring a confirmed source (`"user"`, etc.) for a non-anchor attr. With
no source recorded, the synthesized selector fails that check, drops out
of `array_set_rows` entirely, and the whole array-set wrapper — every
answered mount quantity — vanishes from the preview, even though each one
was individually, genuinely confirmed by the customer.

Fix: `_finalize_grid_selections_from_quantities` (and its caller,
`append_pending_grid_quantities`) now accept an optional `filled_source`
dict and stamp `"user"` on the synthesized selector, threaded through
from every ask_api.py call site's `session.filled_source`.
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _run_cpq_turn_inner
from aryx.cpq.bml.bml import BmlEvaluator
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption
from aryx.api import ask_core_helpers as _ask_core_helpers_test_module


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attrs():
    driver = ConfigAttr(
        entity_id=1, variable_name="mountingArrayControl_viSoln",
        display_label="Mounting Array Control", required=False, default_value="",
        options=[], is_array_control=True,
        array_set_id=100, array_set_role="driver",
        array_set_wrapper_key="_setmountingTypeArrayset_viSoln",
    )
    selector = ConfigAttr(
        entity_id=2, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi",
        options=_opt("Shirt Magnetic Mount", "Jacket Magnetic Mount", "Locking Molle Mount"),
        array_set_id=100, array_set_role="member", array_col_order=1,
    )
    qty_member = ConfigAttr(
        entity_id=3, variable_name="mountingTypeArrayqty_viSoln", display_label="Quantity",
        required=False, default_value="", options=[], select_type="multi",
        array_set_id=100, array_set_role="member", array_col_order=2,
    )
    shirt_qty = ConfigAttr(
        entity_id=4, variable_name="mountingTypeShirtMagneticMountQuantity_viSoln",
        display_label="mounting type Shirt Magnetic Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    jacket_qty = ConfigAttr(
        entity_id=5, variable_name="mountingTypeJacketMagneticMountQuantity_viSoln",
        display_label="mounting type Jacket Magnetic Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    locking_qty = ConfigAttr(
        entity_id=6, variable_name="mountingTypeLockingMolleMountQuantity_viSoln",
        display_label="mounting type Locking Molle Mount Quantity",
        required=False, default_value="", options=[], hidden=True,
    )
    return [driver, selector, qty_member, shirt_qty, jacket_qty, locking_qty]


def _setup(monkeypatch, attrs):
    monkeypatch.setattr(_ask_core_helpers_test_module, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules", lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda *a, **k: (attrs, "Svx Video Remote Speaker Microphone"),
    )


class TestFinalizeStampsFilledSource:
    """Direct unit coverage of the synthesis itself."""

    def _grid_attrs(self):
        return _attrs()

    def test_synthesized_selector_gets_a_user_source_when_given_filled_source(self):
        attrs = self._grid_attrs()
        engine = CpqEngine()
        filled = {
            "mountingTypeShirtMagneticMountQuantity_viSoln": "7",
            "mountingTypeJacketMagneticMountQuantity_viSoln": "8",
            "mountingTypeLockingMolleMountQuantity_viSoln": "3",
        }
        filled_multi: dict = {}
        filled_source: dict = {}
        engine._finalize_grid_selections_from_quantities(attrs, filled, filled_multi, filled_source)
        assert filled_multi["mountingTypeArray_viSoln"] == [
            "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Locking Molle Mount",
        ]
        assert filled_source["mountingTypeArray_viSoln"] == "user"

    def test_omitted_filled_source_stays_a_no_op(self):
        """Backward-compatible default — no filled_source arg, no crash,
        no filled_source dict expected to exist."""
        attrs = self._grid_attrs()
        engine = CpqEngine()
        filled = {
            "mountingTypeShirtMagneticMountQuantity_viSoln": "7",
            "mountingTypeJacketMagneticMountQuantity_viSoln": "8",
            "mountingTypeLockingMolleMountQuantity_viSoln": "3",
        }
        filled_multi: dict = {}
        engine._finalize_grid_selections_from_quantities(attrs, filled, filled_multi)
        assert filled_multi["mountingTypeArray_viSoln"] == [
            "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Locking Molle Mount",
        ]


def test_json_preview_after_full_upfront_flow_includes_the_array_set(monkeypatch):
    """End-to-end reproduction of the live incident: answer every mount's
    quantity one at a time (never directly answering the selector), then
    ask for the JSON preview — it must include every mount, not an empty
    configData."""
    attrs = _attrs()
    _setup(monkeypatch, attrs)

    qty_vns = [
        "mountingTypeShirtMagneticMountQuantity_viSoln",
        "mountingTypeJacketMagneticMountQuantity_viSoln",
        "mountingTypeLockingMolleMountQuantity_viSoln",
    ]
    session = CpqSession(
        mode="cpq", product_name="Svx Video Remote Speaker Microphone",
        country="United States", status="configuring", turn=2,
        filled={}, filled_multi={}, pending_variables=list(qty_vns),
    )
    session_data = session.to_dict()
    for qty in ("7", "8", "3"):
        req = AskRequest(question=qty, workspace_id=1, session_data=session_data)
        resp = _run_cpq_turn_inner(req, object())
        session_data = resp["session_data"]

    session2 = CpqSession.from_dict(session_data)
    assert session2.filled_multi.get("mountingTypeArray_viSoln") == [
        "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Locking Molle Mount",
    ]
    assert session2.filled_source.get("mountingTypeArray_viSoln") == "user", (
        "the synthesized selector must carry a confirmed source, or the "
        "JSON preview's scoped payload build will silently drop it"
    )

    req = AskRequest(question="show me the json", workspace_id=1, session_data=session_data)
    resp = _run_cpq_turn_inner(req, object())
    assert "_setmountingTypeArrayset_viSoln" in resp["answer"], (
        f"the array-set wrapper is missing from the JSON preview: {resp['answer']!r}"
    )
    assert '"mountingTypeArrayqty_viSoln": 7' in resp["answer"]
    assert '"mountingTypeArrayqty_viSoln": 8' in resp["answer"]
    assert '"mountingTypeArrayqty_viSoln": 3' in resp["answer"]
