"""Live-confirmed incident (2026-08-25): quoting the SVX Video Remote
Speaker Microphone, the system-initiated "Mounting Type (mount) or
Mounting Type (Array)?" collision prompt resolves correctly onto
mountingTypeArray_viSoln, but the follow-up question then lists ALL 12
raw catalog mounting options -- the real Motorola CPQ UI (and Aryx's own
constraint rule for this model) narrows this down to 6.

Root cause: both label-collision resolution call sites in ask_api.py
(_run_cpq_turn_inner's mid-configuration "system-initiated" resolver and
its awaiting-approval "options-query" sibling) hardcoded
constrained_item_values=None when building the resolved attr's question
prompt, instead of computing the active constraint set the way the
normal pending-question loop already does via
`constrained_opts.get(next_attr.entity_id)`. next_question_prompt itself
already supports narrowing via constrained_item_values -- the gap was
purely at these two call sites never populating it.

This test drives the actual mid-configuration path (pending_label_
collision_question empty -- the system-initiated shape from this
incident, not the awaiting-approval Q&A one) with a real declarative
ConstraintRule narrowing mountingTypeArray_viSoln's options, and asserts
only the constrained subset appears in the resolved question.
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _run_cpq_turn_inner
from aryx.cpq.bml.bml import BmlEvaluator
from aryx.cpq.state import ConfigAttr, ConstraintRule, CpqSession, MenuOption
from aryx.api import ask_core_helpers as _ask_core_helpers_test_module

_ALL_TWELVE = [
    "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount",
    "Jacket Clip Mount", "Locking Molle Mount", "Magnetic Mount",
    "MOLLE Mount", "Double Molle Mounts", "KF Magnetic Mounts",
    "KF Molle Mounts", "TEK-LOK Belt Mount", "Belt Mount",
]
_VALID_SIX = [
    "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount",
    "Jacket Clip Mount", "Locking Molle Mount", "TEK-LOK Belt Mount",
]


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


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


def test_mid_config_label_collision_resolution_shows_only_constrained_options(monkeypatch):
    model_attr = ConfigAttr(
        entity_id=1, variable_name="modelSelectionSelectModel_viSoln",
        display_label="Select Model", required=False, default_value="",
        select_type="single", options=_opt("VX650 VIDEO RSM TAA", "VX650 VIDEO RSM"),
    )
    single_mount = ConfigAttr(
        entity_id=2, variable_name="mountType_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="single",
        options=_opt("Swivel Clip", "Adjustable Lanyard"),
    )
    multi_mount = ConfigAttr(
        entity_id=3, variable_name="mountingTypeArray_viSoln", display_label="Mounting Type",
        required=False, default_value="", select_type="multi", options=_opt(*_ALL_TWELVE),
    )
    attrs = [model_attr, single_mount, multi_mount]

    con_rule = ConstraintRule(
        rule_name="Constrain certain values for VX650 TAA",
        condition_attr_id=model_attr.entity_id,
        condition_value="VX650 VIDEO RSM TAA",
        target_attr_id=multi_mount.entity_id,
        allowed_values=list(_VALID_SIX),
    )
    _setup(monkeypatch, attrs, [con_rule])

    session = CpqSession(
        mode="cpq", product_name="Svx Video Remote Speaker Microphone",
        country="United States", status="awaiting_approval", turn=2,
        filled={"modelSelectionSelectModel_viSoln": "VX650 VIDEO RSM TAA"},
        pending_label_collision_vns=["mountType_viSoln", "mountingTypeArray_viSoln"],
        pending_label_collision_question="",
    )
    req = AskRequest(
        question="mountingTypeArray_viSoln", workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn_inner(req, object())
    answer = resp["answer"]

    numbered_display_names = [
        ln.split(". ", 1)[1] for ln in answer.splitlines() if ln[:2].rstrip(".").isdigit()
    ]
    for excluded in ("Magnetic Mount", "MOLLE Mount", "Double Molle Mounts",
                     "KF Magnetic Mounts", "KF Molle Mounts", "Belt Mount"):
        assert excluded not in numbered_display_names, (
            f"unconstrained option {excluded!r} leaked into the resolved question: {answer!r}"
        )
    for included in _VALID_SIX:
        assert included in numbered_display_names, f"valid constrained option {included!r} missing: {answer!r}"
    # Precise count: exactly 6 numbered choices, not 12.
    assert len(numbered_display_names) == 6, f"expected 6 numbered options, got: {numbered_display_names}"
