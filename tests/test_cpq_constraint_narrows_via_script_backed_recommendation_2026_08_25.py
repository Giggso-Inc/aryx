"""Regression coverage: a script-backed RecommendationRule whose script
narrows a menu's legal VALUE SET (rather than picking one value) must feed
that narrowing into `apply_constraint_rules`'s output, not be discarded.

Live-verified gap, 2026-08-25 (SVX Mounting Type (Array)): rule
`19435423914` is authored with recommendation mechanics (`set_type != -1`,
per `_load_value_rules`'s own set_type-based classification), so it loads
as a `RecommendationRule`, not a `ConstraintRule`. Its script's actual job
is narrowing `mountingTypeArray_viSoln`'s legal menu from 12 raw catalog
options down to 5 or 6 valid for the current Base Model — a real,
authored business rule. `apply_recommendation_rules` correctly refuses to
auto-pick ONE value from the resulting 5-6 candidates (D2 "never guess"),
but the computed candidate list was then discarded entirely — never
reaching the customer-facing option list, which stayed unfiltered at 12.

Fix: `apply_constraint_rules` accepts an optional `narrowing_rec_rules`
param. A script-backed RecommendationRule whose script evaluates to 2+
values is intersected into the same `constrained` result a genuine
ConstraintRule would produce, via the same `_intersect` helper.
"""
from __future__ import annotations

from aryx.cpq.bml.bml import BmlEvaluator, clear_shared_bml_cache
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption, RecommendationRule

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


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _mounting_type_array() -> ConfigAttr:
    return ConfigAttr(
        entity_id=70284, variable_name="mountingTypeArray_viSoln",
        display_label="Mounting Type", required=False, default_value="",
        select_type="multi",
        options=_menu(
            "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount",
            "Jacket Clip Mount", "Locking Molle Mount", "Magnetic Mount",
            "MOLLE Mount", "Double Molle Mounts", "KF Magnetic Mounts",
            "KF Molle Mounts", "TEK-LOK Belt Mount", "Belt Mount",
        ),
    )


def _narrowing_rule() -> RecommendationRule:
    return RecommendationRule(
        rule_name="Default Values for VX650 Mounting Type Array",
        condition_attr_id=0, condition_value="", target_attr_id=70284,
        script=_MOUNT_NARROWING_SCRIPT,
    )


def setup_function(_fn):
    clear_shared_bml_cache()


def test_script_backed_recommendation_narrows_options_when_ambiguous():
    attr = _mounting_type_array()
    eng = CpqEngine()
    bml_eval = BmlEvaluator({})
    filled = {"modelSelectionSelectModel_viSoln": "SVX Video Remote Speaker Mic"}

    result = eng.apply_constraint_rules(
        [attr], [], filled, bml_eval=bml_eval,
        narrowing_rec_rules=[_narrowing_rule()],
    )

    assert result.get(70284) == [
        "Shirt Magnetic Mount", "Jacket Magnetic Mount", "Shirt Clip Mount",
        "Jacket Clip Mount", "Locking Molle Mount",
    ]


def test_script_backed_recommendation_ignored_when_it_resolves_to_one_value():
    """A script resolving to exactly one value is apply_recommendation_
    rules' job to pick, not a narrowing case — must not appear here."""
    attr = _mounting_type_array()
    eng = CpqEngine()
    bml_eval = BmlEvaluator({})
    single_value_rule = RecommendationRule(
        rule_name="Single value rule", condition_attr_id=0, condition_value="",
        target_attr_id=70284, script='return "Shirt Magnetic Mount";',
    )

    result = eng.apply_constraint_rules(
        [attr], [], {}, bml_eval=bml_eval,
        narrowing_rec_rules=[single_value_rule],
    )

    assert 70284 not in result


def test_narrowing_rec_rules_is_a_no_op_by_default():
    """Every pre-existing caller (doesn't pass this param) is unaffected."""
    attr = _mounting_type_array()
    eng = CpqEngine()
    bml_eval = BmlEvaluator({})

    result = eng.apply_constraint_rules([attr], [], {}, bml_eval=bml_eval)

    assert result == {}


def test_narrowing_rec_rules_skips_already_filled_targets_without_evaluating_script():
    """Live-confirmed perf regression (2026-08-25, APX Next): this loop
    was missing the same "already filled -> skip" guard
    apply_recommendation_rules already has, so it evaluated the
    expensive script for ALL script-backed recommendation rules every
    pass regardless of fill state -- confirmed live this cost 82s/59s/
    37s across the first 3 passes for a 1091-rule catalog before the
    per-pass constraint cache stabilized.

    Uses the real, parseable _MOUNT_NARROWING_SCRIPT-equivalent rule
    (via _narrowing_rule()), which genuinely resolves to 5 values when
    actually evaluated against this filled state (confirmed elsewhere
    in this file) -- so `70284 not in result` only passes if the guard
    skipped evaluating it entirely because its target
    (mountingTypeArray_viSoln) is already filled; pre-fix, this same
    assertion fails because the script WOULD have been evaluated and
    narrowed the result regardless of fill state."""
    attr = _mounting_type_array()
    eng = CpqEngine()
    bml_eval = BmlEvaluator({})
    rule = _narrowing_rule()
    filled = {
        "modelSelectionSelectModel_viSoln": "SVX Video Remote Speaker Mic",
        "mountingTypeArray_viSoln": "Shirt Magnetic Mount",
    }

    result = eng.apply_constraint_rules(
        [attr], [], filled, bml_eval=bml_eval, narrowing_rec_rules=[rule],
    )

    assert 70284 not in result
