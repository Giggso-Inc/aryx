"""Unit tests for detect_attr_activation (D2) and detect_attr_clear (D4).

docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md — post-quote Q&A/editing plan.
Both detectors are gated the same way: never a required attr, never a
bypass of a currently-active rule (checked live against current state,
not a cached/stale flag).
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, ConstraintRule, HidingRule, MenuOption, RecommendationRule


def _attr(
    eid: int, vn: str, label: str, *, required: bool = False, hidden: bool = False,
    select_type: str = "single", options: list[MenuOption] | None = None,
) -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label,
        required=required, default_value="", hidden=hidden,
        select_type=select_type, options=options or [],
    )


def _opts(*values: str) -> list[MenuOption]:
    return [MenuOption(v, v, i) for i, v in enumerate(values)]


# ── detect_attr_activation (D2) ─────────────────────────────────────────────

def test_u1_matches_a_declined_optional_multi_select():
    attr = _attr(1, "mountingTypeArray_viSoln", "Mounting Type",
                 select_type="multi", options=_opts("Shirt", "Jacket"))
    engine = CpqEngine()
    result = engine.detect_attr_activation(
        "add mounting type", [attr], filled={}, filled_multi={},
        hiding_rules=[], workspace_id=1, catalog_prefix="",
    )
    assert result is attr


def test_u2_matches_a_flow_exclusion_dropped_optional_attr():
    """payload_flow_exclusions only ever returns product/model identity
    attrs — this proves detect_attr_activation's unified predicate admits
    one when it's required==False, without needing a separate code path."""
    engine = CpqEngine()
    attr = _attr(1, "modelname_all", "Model Name", options=_opts("X1"))
    result = engine.detect_attr_activation(
        "add model name", [attr], filled={}, filled_multi={},
        hiding_rules=[], workspace_id=1, catalog_prefix="",
    )
    assert result is attr


def test_u3_matches_a_hiding_rule_excluded_attr_whose_condition_no_longer_holds():
    cond = _attr(1, "region", "Region", options=_opts("NA", "EU"))
    target = _attr(2, "extendedWarranty", "Extended Warranty", options=_opts("Y"))
    engine = CpqEngine()
    # Hide extendedWarranty only when region=="EU" — with region now "NA",
    # the condition doesn't match, so the attr is currently visible
    # (no longer hidden), the D2 case-3 scenario.
    hide_rule = HidingRule("hide warranty in EU", 1, "EU", 2, hide=True)
    result = engine.detect_attr_activation(
        "add extended warranty", [cond, target], filled={"region": "NA"},
        filled_multi={}, hiding_rules=[hide_rule], workspace_id=1, catalog_prefix="",
    )
    assert result is target


def test_u4_rejects_a_required_attr_in_any_pool():
    attr = _attr(1, "hwVersion", "Hardware Version", required=True, options=_opts("A"))
    engine = CpqEngine()
    result = engine.detect_attr_activation(
        "add hardware version", [attr], filled={}, filled_multi={},
        hiding_rules=[], workspace_id=1, catalog_prefix="",
    )
    assert result is None


def test_u5_rejects_an_attr_whose_hiding_condition_is_still_true():
    cond = _attr(1, "region", "Region", options=_opts("NA", "EU"))
    target = _attr(2, "extendedWarranty", "Extended Warranty", options=_opts("Y"))
    hide_rule = HidingRule("hide warranty in EU", 1, "EU", 2, hide=True)
    engine = CpqEngine()
    result = engine.detect_attr_activation(
        "add extended warranty", [cond, target], filled={"region": "EU"},
        filled_multi={}, hiding_rules=[hide_rule], workspace_id=1, catalog_prefix="",
    )
    assert result is None, "the rule-bypass guard must hold: still-hidden attrs are never addable"


def test_u6_rejects_a_bm_native_hidden_attr():
    attr = _attr(1, "internalFlag", "Internal Flag", hidden=True, options=_opts("Y"))
    engine = CpqEngine()
    result = engine.detect_attr_activation(
        "add internal flag", [attr], filled={}, filled_multi={},
        hiding_rules=[], workspace_id=1, catalog_prefix="",
    )
    assert result is None


def test_u7_rejects_an_already_filled_attr():
    attr = _attr(1, "batteryType", "Battery Type", options=_opts("Standard"))
    engine = CpqEngine()
    result = engine.detect_attr_activation(
        "add battery type", [attr], filled={"batteryType": "Standard"},
        filled_multi={}, hiding_rules=[], workspace_id=1, catalog_prefix="",
    )
    assert result is None


def test_u8_fuzzy_label_match_still_works():
    """_label_mentioned tolerates DROPPED LEADING words (e.g. a generic
    "mounting type" prefix a user naturally omits) — mirrors the same
    tolerance every other change-request detector in this file relies on."""
    attr = _attr(1, "extendedWarrantyPlan", "Extended Warranty Plan", options=_opts("Y"))
    engine = CpqEngine()
    result = engine.detect_attr_activation(
        "add warranty plan", [attr], filled={}, filled_multi={},
        hiding_rules=[], workspace_id=1, catalog_prefix="",
    )
    assert result is attr


def test_activation_requires_an_add_verb():
    attr = _attr(1, "extendedWarranty", "Extended Warranty", options=_opts("Y"))
    engine = CpqEngine()
    result = engine.detect_attr_activation(
        "what is extended warranty", [attr], filled={}, filled_multi={},
        hiding_rules=[], workspace_id=1, catalog_prefix="",
    )
    assert result is None


# ── detect_attr_clear (D4) ───────────────────────────────────────────────────

def test_u9_matches_a_filled_optional_non_rule_forced_single_select():
    attr = _attr(1, "batteryType", "Battery Type", options=_opts("Standard", "Extended"))
    engine = CpqEngine()
    result = engine.detect_attr_clear(
        "clear battery type", [attr], filled={"batteryType": "Standard"},
        rec_rules=[], con_rules=[],
    )
    assert result is attr


def test_u10_rejects_a_required_attr():
    attr = _attr(1, "hwVersion", "Hardware Version", required=True,
                 options=_opts("A", "B"))
    engine = CpqEngine()
    result = engine.detect_attr_clear(
        "clear hardware version", [attr], filled={"hwVersion": "A"},
        rec_rules=[], con_rules=[],
    )
    assert result is None


def test_u11_rejects_an_attr_currently_forced_by_a_still_active_rule():
    cond = _attr(1, "region", "Region", options=_opts("NA"))
    target = _attr(2, "solutionType", "Solution Type", options=_opts("CloudRC", "Other"))
    rec = RecommendationRule("set cloud rc", 1, "NA", 2, "CloudRC")
    engine = CpqEngine()
    result = engine.detect_attr_clear(
        "clear solution type", [cond, target],
        filled={"region": "NA", "solutionType": "CloudRC"},
        rec_rules=[rec], con_rules=[],
    )
    assert result is None, "a still-active recommendation must block clearing"


def test_u12_matches_an_attr_whose_forcing_rule_no_longer_holds():
    cond = _attr(1, "region", "Region", options=_opts("NA", "EU"))
    target = _attr(2, "solutionType", "Solution Type", options=_opts("CloudRC", "Other"))
    rec = RecommendationRule("set cloud rc in NA", 1, "NA", 2, "CloudRC")
    engine = CpqEngine()
    # region has since changed to EU — the NA-only recommendation no
    # longer fires, so the previously rule-set value is now clearable.
    result = engine.detect_attr_clear(
        "clear solution type", [cond, target],
        filled={"region": "EU", "solutionType": "CloudRC"},
        rec_rules=[rec], con_rules=[],
    )
    assert result is target


def test_u13_rejects_an_attr_with_no_value_to_clear():
    attr = _attr(1, "batteryType", "Battery Type", options=_opts("Standard"))
    engine = CpqEngine()
    result = engine.detect_attr_clear(
        "clear battery type", [attr], filled={}, rec_rules=[], con_rules=[],
    )
    assert result is None


def test_u14_rejects_a_multi_select_attr():
    attr = _attr(1, "mountingTypeArray_viSoln", "Mounting Type", select_type="multi",
                 options=_opts("Shirt", "Jacket"))
    engine = CpqEngine()
    result = engine.detect_attr_clear(
        "clear mounting type", [attr], filled={"mountingTypeArray_viSoln": "Shirt"},
        rec_rules=[], con_rules=[],
    )
    assert result is None


def test_clear_rejects_a_constraint_narrowed_to_one_remaining_option():
    cond = _attr(1, "productLine", "Product Line", options=_opts("Basic"))
    target = _attr(2, "colorOption", "Color Option", options=_opts("Black", "White"))
    con = ConstraintRule("only black for basic", 1, "Basic", 2, ["Black"])
    engine = CpqEngine()
    result = engine.detect_attr_clear(
        "clear color option", [cond, target],
        filled={"productLine": "Basic", "colorOption": "Black"},
        rec_rules=[], con_rules=[con],
    )
    assert result is None, "a constraint narrowing to exactly one option would immediately refill it"


# ── Regression: _label_mentioned's word-set fallback degrading to a
# single generic shared word (D2/D4 have no secondary value-match
# backstop, unlike detect_change_request) ──────────────────────────────────

def test_clear_does_not_false_positive_on_a_shared_generic_word():
    """Live-verified bug: "clear surveillance package type" (meant for
    "Surveillance Package Type") instead matched an unrelated "Customer
    Type" attr via _label_mentioned's word-set tier degrading to the
    single shared word "type". Fixed by using _label_mentioned_strict,
    which never drops a 2-word label down to one word."""
    target = _attr(1, "spSurveillancePackagesType_astro", "Surveillance Package Type",
                    options=_opts("Beige", "Black"))
    decoy = _attr(2, "isCustomerTypeFEDERAL_astro", "Customer Type",
                   options=_opts("Yes", "No"))
    engine = CpqEngine()
    result = engine.detect_attr_clear(
        "clear surveillance package type", [decoy, target],
        filled={"spSurveillancePackagesType_astro": "Beige",
                "isCustomerTypeFEDERAL_astro": "No"},
        rec_rules=[], con_rules=[],
    )
    assert result is target, "must match the real target, never the unrelated 2-word-label decoy"


def test_activation_does_not_false_positive_on_a_shared_generic_word():
    target = _attr(1, "spSurveillancePackagesType_astro", "Surveillance Package Type",
                    options=_opts("Beige", "Black"))
    decoy = _attr(2, "isCustomerTypeFEDERAL_astro", "Customer Type", options=_opts("Yes", "No"))
    engine = CpqEngine()
    result = engine.detect_attr_activation(
        "add surveillance package type", [decoy, target], filled={}, filled_multi={},
        hiding_rules=[], workspace_id=1, catalog_prefix="",
    )
    assert result is target, "must match the real target, never the unrelated 2-word-label decoy"


# ── detect_approval regression pin (raven review on PR #192) ───────────────
# The original fix for "great question about mounting" false-positiving as
# approval (docs/CPQ_ASK_OFFTOPIC_INTENT_FALSE_POSITIVE_FIXES_2026-08-13.md
# D42) replaced bare great/perfect keywords with a whole-message-only
# pattern, which correctly killed the false positive but also broke
# previously-working combined phrasings like "Great, let's go" and
# "Perfect, that works" that the pre-fix regex used to match. For
# session.guided_mode=True sessions — which never reach the LLM-first
# gateway that papers over this for everyone else (ask_api.py's STEP-6
# gate checks `not session.guided_mode`) — that was a real behavior
# regression, not just a documented gap. Loosened the standalone pattern to
# accept the two natural trailing clauses ("let's go" / "that's
# works/good/right") while keeping the false-positive fix intact.
def test_detect_approval_accepts_combined_great_perfect_phrasing():
    engine = CpqEngine()
    for text in ("Great, let's go", "Perfect, that works", "Perfect, let's go",
                 "Great!", "Perfect."):
        assert engine.detect_approval(text), f"must approve: {text!r}"


def test_detect_approval_still_rejects_great_as_a_pleasantry():
    engine = CpqEngine()
    for text in ("great question about mounting", "greatly appreciated"):
        assert not engine.detect_approval(text), f"must not approve: {text!r}"
