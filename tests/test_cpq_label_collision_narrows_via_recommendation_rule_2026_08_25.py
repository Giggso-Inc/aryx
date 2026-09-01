"""Regression coverage for the real-world shape of the 2026-08-25 SVX
"Mounting Type (Array)" incident: the narrowing rule that survives in
production isn't a declarative `ConstraintRule` (already covered by
test_cpq_label_collision_resolution_respects_constraints_2026_08_25.py) --
it's rule `19435423914`, a script-backed `RecommendationRule` that
`_load_value_rules` classifies as a recommendation (set_type != -1) even
though its script narrows a menu rather than picking one value (see
test_cpq_constraint_narrows_via_script_backed_recommendation_2026_08_25.py
for the engine-level half of this fix).

`apply_constraint_rules` already knows how to fold such a rule's narrowed
candidate list into its result via its `narrowing_rec_rules` param -- but
both label-collision resolution call sites in `_run_cpq_turn_inner`
(the awaiting-approval "options-query" resolver and its mid-configuration
"system-initiated" sibling) called it without passing `rec_rules` through,
so a customer resolving a same-labeled collision onto a rec-rule-narrowed
attribute still saw the full raw catalog. This exercises BOTH call sites
end-to-end with a script -- not a hardcoded allow-list, not a regex --
mirroring the actual authored SVX rule shape.
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _run_cpq_turn_inner
from aryx.cpq.bml import BmlEvaluator, clear_shared_bml_cache
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption, RecommendationRule

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

# The actual authored SVX narrowing script (rule 19435423914), reproduced
# verbatim from the live catalog export -- a script the engine EVALUATES,
# not a value list Aryx special-cases by name.
_MOUNT_NARROWING_SCRIPT = (
    'if(modelSelectionSelectModel_viSoln=="SVX VIDEO REMOTE SPEAKER MIC UL"){\n'
    'retVal ="Shirt Magnetic Mount"|"Jacket Magnetic Mount"|"Shirt Clip Mount"'
    '|"Jacket Clip Mount"|"Locking Molle Mount"|"TEK-LOK Belt Mount";\n'
    '}\n'
    'else\n{\n'
    'retVal ="Shirt Magnetic Mount"|"Jacket Magnetic Mount"|"Shirt Clip Mount"'
    '|"Jacket Clip Mount"|"Locking Molle Mount";\n'
    '}'
)


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attrs():
    model_attr = ConfigAttr(
        entity_id=1, variable_name="modelSelectionSelectModel_viSoln",
        display_label="Select Model", required=False, default_value="",
        select_type="single", options=_opt("SVX Video Remote Speaker Mic", "SVX VIDEO REMOTE SPEAKER MIC UL"),
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
    return model_attr, single_mount, multi_mount


def _narrowing_rule(target_attr_id: int) -> RecommendationRule:
    return RecommendationRule(
        rule_name="Default Values for VX650 Mounting Type Array",
        condition_attr_id=0, condition_value="", target_attr_id=target_attr_id,
        script=_MOUNT_NARROWING_SCRIPT,
    )


def _setup(monkeypatch, attrs, rec_rules):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules",
        lambda *a, **k: (rec_rules, []),
    )
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda *a, **k: (attrs, "Svx Video Remote Speaker Microphone"),
    )


def _numbered_options(answer: str) -> list[str]:
    return [ln.split(". ", 1)[1] for ln in answer.splitlines() if ln[:2].rstrip(".").isdigit()]


def setup_function(_fn):
    clear_shared_bml_cache()


def test_mid_config_collision_resolution_narrows_via_script_backed_recommendation_rule(monkeypatch):
    """The system-initiated, mid-configuration path (_pqc_* in
    ask_api.py) -- session.status stays default ('cpq'), pending_label_
    collision_question is empty."""
    model_attr, single_mount, multi_mount = _attrs()
    attrs = [model_attr, single_mount, multi_mount]
    _setup(monkeypatch, attrs, [_narrowing_rule(multi_mount.entity_id)])

    session = CpqSession(
        product_name="Svx Video Remote Speaker Microphone", country="United States", turn=2,
        filled={"modelSelectionSelectModel_viSoln": "SVX VIDEO REMOTE SPEAKER MIC UL"},
        pending_label_collision_vns=["mountType_viSoln", "mountingTypeArray_viSoln"],
        pending_label_collision_question="",
    )
    req = AskRequest(
        question="mountingTypeArray_viSoln", workspace_id=1, session_data=session.to_dict(),
    )

    resp = _run_cpq_turn_inner(req, object())
    numbered = _numbered_options(resp["answer"])

    assert sorted(numbered) == sorted(_VALID_SIX), (
        f"expected only the 6 script-narrowed options, got: {numbered}"
    )


def test_awaiting_approval_options_query_collision_narrows_via_script_backed_recommendation_rule(monkeypatch):
    """The awaiting-approval "options-query" resolver (_lc_* in
    ask_api.py) -- system-initiated shape, no original Q&A question to
    resume (_lc_orig_question empty)."""
    model_attr, single_mount, multi_mount = _attrs()
    attrs = [model_attr, single_mount, multi_mount]
    _setup(monkeypatch, attrs, [_narrowing_rule(multi_mount.entity_id)])

    session = CpqSession(
        product_name="Svx Video Remote Speaker Microphone", country="United States",
        status="awaiting_approval", turn=2,
        filled={"modelSelectionSelectModel_viSoln": "SVX VIDEO REMOTE SPEAKER MIC UL"},
        pending_label_collision_vns=["mountType_viSoln", "mountingTypeArray_viSoln"],
        pending_label_collision_question="",
    )
    req = AskRequest(
        question="mountingTypeArray_viSoln", workspace_id=1, session_data=session.to_dict(),
    )

    resp = _run_cpq_turn_inner(req, object())
    numbered = _numbered_options(resp["answer"])

    assert sorted(numbered) == sorted(_VALID_SIX), (
        f"expected only the 6 script-narrowed options, got: {numbered}"
    )
