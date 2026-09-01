"""Live-confirmed gap (2026-08-26, SVX Video Remote Speaker Microphone):
quoting the BASE model "SVX Video Remote Speaker Mic" (which the real
native UI, and this catalog's own constraint rule, narrows to only 5
valid mounts — no TEK-LOK Belt Mount, that's TAA-only) still asked for
"Mounting type TEK-LOK Belt Mount Quantity" through the upfront
per-option flow.

Root cause: resolve_pending_grid_quantities (and its caller chain,
_finalize_grid_selections_from_quantities / append_pending_grid_
quantities) seeded a quantity question for EVERY raw catalog option
resolve_array_grid_links could token-match against the selector's full
option list -- never filtered against the active constraint rule the
normal "choose one" pending-question path already narrows its own list
with.

Fix: all three now accept an optional constrained_opts dict (the same
apply_constraint_rules output, keyed by entity_id, the normal pending
loop already threads through) and only ever seed/finalize options within
that narrowed set when one is active for the selector.
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _run_cpq_turn_inner
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, ConstraintRule, CpqSession, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


_BASE_VALID = [
    "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount",
    "Jacket Clip Mount", "Locking Molle Mount",
]


def _attrs():
    model_attr = ConfigAttr(
        entity_id=1, variable_name="modelSelectionSelectModel_viSoln", display_label="Select Model",
        required=False, default_value="", select_type="single",
        options=_opt("SVX Video Remote Speaker Mic", "SVX Video Remote Speaker Mic TAA"),
    )
    selector = ConfigAttr(
        entity_id=2, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi",
        options=_opt(*_BASE_VALID, "TEK-LOK Belt Mount"),
    )
    names_with_own_qty = [*_BASE_VALID, "TEK-LOK Belt Mount"]
    qty_attrs = [
        ConfigAttr(
            entity_id=10 + i,
            variable_name="mountingType" + nm.replace(" ", "").replace("-", "") + "Quantity_viSoln",
            display_label=f"mounting type {nm} Quantity",
            required=False, default_value="", options=[], hidden=True,
        )
        for i, nm in enumerate(names_with_own_qty)
    ]
    return [model_attr, selector, *qty_attrs]


def _base_model_constraint():
    return ConstraintRule(
        rule_name="Constrain mounts for base model",
        condition_attr_id=1, condition_value="SVX Video Remote Speaker Mic",
        target_attr_id=2, allowed_values=list(_BASE_VALID),
    )


def _setup(monkeypatch, attrs, con_rules):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules", lambda *a, **k: ([], con_rules))
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda *a, **k: (attrs, "Svx Video Remote Speaker Microphone"),
    )


class TestEngineLevelConstraintNarrowing:
    def test_resolve_pending_grid_quantities_respects_constrained_opts(self):
        attrs = _attrs()
        engine = CpqEngine()
        selector = next(a for a in attrs if a.variable_name == "mountingTypeArray_viSoln")
        constrained_opts = {selector.entity_id: list(_BASE_VALID)}
        extra = engine.resolve_pending_grid_quantities(attrs, {}, {}, constrained_opts)
        extra_vns = {a.variable_name for a in extra}
        assert "mountingTypeTEKLOKBeltMountQuantity_viSoln" not in extra_vns, (
            "TEK-LOK Belt Mount is not valid for the base model -- it must "
            "never be seeded as a pending quantity question"
        )
        assert len(extra_vns) == 5

    def test_finalize_only_requires_the_constrained_options_answered(self):
        attrs = _attrs()
        engine = CpqEngine()
        selector = next(a for a in attrs if a.variable_name == "mountingTypeArray_viSoln")
        constrained_opts = {selector.entity_id: list(_BASE_VALID)}
        filled = {
            "mountingTypeShirtMagneticMountQuantity_viSoln": "7",
            "mountingTypeJacketMagneticMountQuantity_viSoln": "8",
            "mountingTypeShirtClipMountQuantity_viSoln": "1",
            "mountingTypeJacketClipMountQuantity_viSoln": "2",
            "mountingTypeLockingMolleMountQuantity_viSoln": "3",
            # TEK-LOK deliberately NOT answered -- must not block finalize.
        }
        filled_multi: dict = {}
        engine._finalize_grid_selections_from_quantities(
            attrs, filled, filled_multi, constrained_opts=constrained_opts)
        assert filled_multi.get("mountingTypeArray_viSoln") == _BASE_VALID


def test_base_model_upfront_flow_never_asks_for_the_taa_only_mount(monkeypatch):
    attrs = _attrs()
    con_rules = [_base_model_constraint()]
    _setup(monkeypatch, attrs, con_rules)

    session = CpqSession(
        mode="cpq", product_name="Svx Video Remote Speaker Microphone",
        country="United States", status="configuring", turn=2,
        filled={"modelSelectionSelectModel_viSoln": "SVX Video Remote Speaker Mic"},
        filled_source={"modelSelectionSelectModel_viSoln": "user"},
        filled_multi={},
        pending_variables=["mountingTypeShirtMagneticMountQuantity_viSoln"],
    )
    session_data = session.to_dict()
    for qty in ("7", "8", "1", "2", "3"):
        req = AskRequest(question=qty, workspace_id=1, session_data=session_data)
        resp = _run_cpq_turn_inner(req, object())
        session_data = resp["session_data"]
        assert "TEK-LOK" not in (resp.get("answer") or ""), (
            f"the base model must never be asked for the TAA-only mount: {resp['answer']!r}"
        )

    session2 = CpqSession.from_dict(session_data)
    assert session2.status == "awaiting_approval", (
        "the base model's configuration must be complete after only its "
        "5 real mounts are answered -- TEK-LOK Belt Mount is not one of them"
    )
    assert session2.filled_multi.get("mountingTypeArray_viSoln") == _BASE_VALID
    assert "mountingTypeTEKLOKBeltMountQuantity_viSoln" not in session2.filled
