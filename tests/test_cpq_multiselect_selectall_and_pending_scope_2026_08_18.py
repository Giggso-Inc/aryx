"""Regression tests for the 2026-08-18 fixes:

Issue 1 — auto_fill()'s multi-select "CONSTRAINED but ambiguous" branch
(a real rule narrows the attr to 2+ options, nothing resolves it to one)
now selects ALL currently-allowed options instead of leaving the attr
empty (2026-08-18 HITL override of the prior "never guess" default).

Issue 3 — same root cause/fix as Issue 1, exercised against the real
catalog variable_names reported asking live (relatedServicesType_astro,
promoApplicationServices_astro) so a rename/refactor of the branch can't
silently regress the exact attrs the live bug was reported against.

Issue 4 — `_reask_confirmed_data_table_conflict()` (src/aryx/api/
ask_api.py) now calls `set_pending_scope()` with the freshly-expanded
option list it just showed the customer, so the customer's next reply is
validated against that list instead of whatever `pending_scope_candidates`
held from a prior, narrower turn.

Issue 2 — a decision-anchor attr (country/region/hardware version/
product) whose customer-confirmed value was dropped THIS SAME pass
(a real constraint narrowed it away) no longer gets silently reasserted
to a DIFFERENT value by a same-turn satisfied recommendation rule --
falls through to `pending` (re-ask) instead of overwriting the
customer's real answer with no re-ask and no warning.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.api.ask_api import _reask_confirmed_data_table_conflict
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption, RecommendationRule


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _non_satisfying_rec_rule(target_entity_id: int) -> RecommendationRule:
    """A real recommendation rule DOES target this attr in the live
    catalog (that's what makes `_no_real_fill_justification` return False
    and let the attr reach the multi-select "CONSTRAINED but ambiguous"
    branch at all) -- but its condition never holds in these fixtures, so
    it never resolves the value itself via `_satisfied_recommendation`.
    Condition references an attr (id 999) that's never in `already_filled`."""
    return RecommendationRule(
        rule_name="unrelated condition, never satisfied",
        condition_attr_id=999, condition_value="NEVER_MATCHES",
        target_attr_id=target_entity_id,
        conditions=[(999, "NEVER_MATCHES", "4")],
        recommended_value="__unused__",
    )


# ── Issue 1 ──────────────────────────────────────────────────────────────

def test_multiselect_constrained_ambiguous_selects_all_allowed_options():
    """A real rule narrows a multi-select attr to 2 of 3 real options and
    nothing (recommendation/default) resolves it to exactly one -- must
    now select ALL of the narrowed set instead of leaving it empty."""
    attr = ConfigAttr(entity_id=1, variable_name="m", display_label="M",
                       required=False, default_value="", select_type="multi",
                       options=_menu("V1", "V2", "V3"))
    eng = CpqEngine()
    filled_multi: dict = {}
    eng.auto_fill(
        [attr], {}, already_filled_multi=filled_multi,
        constrained_opts={1: ["V1", "V2"]}, display_order={"m": 0},
        rec_rules=[_non_satisfying_rec_rule(1)],
    )
    assert sorted(filled_multi.get("m", [])) == ["V1", "V2"]


def test_multiselect_constrained_ambiguous_excludes_the_ruled_out_option():
    """The one option the active constraint excluded (V3) must never be
    selected, even though "select all" is now the default for the
    surviving set."""
    attr = ConfigAttr(entity_id=1, variable_name="m", display_label="M",
                       required=False, default_value="", select_type="multi",
                       options=_menu("V1", "V2", "V3"))
    eng = CpqEngine()
    filled_multi: dict = {}
    eng.auto_fill(
        [attr], {}, already_filled_multi=filled_multi,
        constrained_opts={1: ["V1", "V2"]}, display_order={"m": 0},
        rec_rules=[_non_satisfying_rec_rule(1)],
    )
    assert "V3" not in filled_multi.get("m", [])


def test_multiselect_unconstrained_case_unchanged_by_issue1_fix():
    """Sibling regression guard: a genuinely UNCONSTRAINED multi-select
    under a loaded layout map must still be left unfilled (existing
    test_multiselect_first_available_skipped_when_layout_loaded behavior)
    -- Issue 1's fix only touches the CONSTRAINED-but-ambiguous branch."""
    attr = ConfigAttr(entity_id=1, variable_name="m", display_label="M",
                       required=False, default_value="", select_type="multi",
                       options=_menu("V1", "V2"))
    eng = CpqEngine()
    filled_multi: dict = {}
    eng.auto_fill([attr], {}, already_filled_multi=filled_multi, display_order={"m": 0})
    assert "m" not in filled_multi


# ── Issue 3 (same mechanism, real live-reported variable_names) ─────────

def test_relatedservicestype_astro_selects_all_when_constrained_and_ambiguous():
    attr = ConfigAttr(
        entity_id=10, variable_name="relatedServicesType_astro",
        display_label="Service Type", required=False, default_value="",
        select_type="multi",
        options=_menu("INSTALLATION", "RENTAL", "REPAIR", "SOFTWARE"),
    )
    eng = CpqEngine()
    filled_multi: dict = {}
    eng.auto_fill(
        [attr], {}, already_filled_multi=filled_multi,
        constrained_opts={10: ["INSTALLATION", "REPAIR"]},
        display_order={"relatedServicesType_astro": 0},
        rec_rules=[_non_satisfying_rec_rule(10)],
    )
    assert sorted(filled_multi.get("relatedServicesType_astro", [])) == [
        "INSTALLATION", "REPAIR",
    ]


def test_promoapplicationservices_astro_selects_all_when_constrained_and_ambiguous():
    attr = ConfigAttr(
        entity_id=11, variable_name="promoApplicationServices_astro",
        display_label="Promo Application Services", required=False, default_value="",
        select_type="multi",
        options=_menu("SmartProgramming", "SmartConnect", "SmartMapping"),
    )
    eng = CpqEngine()
    filled_multi: dict = {}
    eng.auto_fill(
        [attr], {}, already_filled_multi=filled_multi,
        constrained_opts={11: ["SmartConnect", "SmartMapping"]},
        display_order={"promoApplicationServices_astro": 0},
        rec_rules=[_non_satisfying_rec_rule(11)],
    )
    assert sorted(filled_multi.get("promoApplicationServices_astro", [])) == [
        "SmartConnect", "SmartMapping",
    ]


# ── Issue 4 ───────────────────────────────────────────────────────────────

def test_confirmed_conflict_reask_syncs_pending_scope_to_expanded_options():
    """Live bug: after a rule conflict re-asks Package Type with an
    EXPANDED option list, the customer's verbatim reply from that list
    ("Single XE") was rejected because `pending_scope_candidates` still
    held the narrower list from before the conflict was detected. The
    re-ask must sync pending_scope to the exact options it just showed."""
    package_type_attr = ConfigAttr(
        entity_id=1, variable_name="packageTypeBundles_astro",
        display_label="Package Type", required=False, default_value="",
        select_type="multi",
        options=_menu(
            "Single", "Bulk", "N/A", "Demo Kit Case", "Single XE",
            "Bulk XE", "Pack into Demo Kit Case", "Single Pack Clamshell",
        ),
    )
    product_attr = ConfigAttr(
        entity_id=2, variable_name="productSelectionProduct_all",
        display_label="Product", required=False, default_value="",
        select_type="single", options=_menu("APX NEXT XE"),
    )
    attrs = [package_type_attr, product_attr]

    session = CpqSession()
    session.filled = {
        "packageTypeBundles_astro": "Single Pack Clamshell",
        "productSelectionProduct_all": "APX NEXT XE",
    }
    session.display_filled = dict(session.filled)
    session.filled_source = {
        "packageTypeBundles_astro": "user",
        "productSelectionProduct_all": "user",
    }
    # A STALE, narrower scope left over from the turn BEFORE the conflict
    # was detected -- this is exactly what must be overwritten by the fix.
    session.pending_scope_kind = "attr_options"
    session.pending_scope_candidates = ["Single Pack Clamshell"]
    session.pending_variables = []

    conflict_pair = {
        ("packageTypeBundles_astro", "productSelectionProduct_all"),
    }
    with patch.object(
        CpqEngine, "find_confirmed_data_table_conflicts", return_value=conflict_pair,
    ):
        result = _reask_confirmed_data_table_conflict(
            session, attrs, workspace_id=7, catalog_prefix="",
        )

    assert result is not None
    assert "Rule conflict detected" in result
    # The fix: pending_scope_candidates must now be the FULL expanded
    # 8-item option list just shown, not the stale 1-item list.
    assert session.pending_scope_candidates is not None
    assert "Single XE" in session.pending_scope_candidates
    assert len(session.pending_scope_candidates) == 8
    assert session.pending_scope_kind == "attr_options"


# ── Issue 2 ───────────────────────────────────────────────────────────────

def test_decision_anchor_dropped_value_is_reasked_not_silently_reassigned():
    """Live bug, confirmed via direct repro: after a real constraint drops
    a customer-confirmed decision-anchor value (country/region/hardware
    version/product), a same-turn SATISFIED recommendation rule must not
    silently refill it with a DIFFERENT value -- the customer's real
    answer must be re-asked, not overwritten with no warning."""
    country_attr = ConfigAttr(
        entity_id=1, variable_name="ultimateDestinationCountry",
        display_label="Ultimate Destination Country", required=False,
        default_value="", select_type="single",
        options=_menu("US", "Canada", "Mexico"),
    )
    cond_attr = ConfigAttr(
        entity_id=2, variable_name="cond", display_label="Cond",
        required=False, default_value="", select_type="single",
        options=_menu("X"),
    )
    rec_rule = RecommendationRule(
        rule_name="Recommendation rule to set ultimateDestinationCountry",
        condition_attr_id=2, condition_value="X", target_attr_id=1,
        conditions=[(2, "X", "4")], recommended_value="Canada",
    )
    eng = CpqEngine()
    filled = {"ultimateDestinationCountry": "US", "cond": "X"}
    filled_source = {"ultimateDestinationCountry": "user", "cond": "user"}

    ret_filled, _display, pending = eng.auto_fill(
        [country_attr, cond_attr], {}, already_filled=filled, filled_source=filled_source,
        constrained_opts={1: ["Canada", "Mexico"]},  # "US" no longer allowed
        rec_rules=[rec_rule],
    )

    assert "ultimateDestinationCountry" not in ret_filled, (
        "customer's dropped answer must not be silently reassigned to a "
        "different value by the recommendation rule"
    )
    assert any(a.variable_name == "ultimateDestinationCountry" for a in pending), (
        "must be re-asked instead of silently overwritten"
    )


def test_non_anchor_attr_recommendation_reassert_is_unaffected():
    """Sibling regression guard: the fix is narrowly scoped to decision-
    anchor attrs (_DECISION_ANCHOR_VNS) -- an ordinary governed attr whose
    dropped value gets reasserted by a satisfied recommendation rule must
    still fill normally, unaffected by Issue 2's fix."""
    ordinary_attr = ConfigAttr(
        entity_id=1, variable_name="someOrdinaryAttr_astro",
        display_label="Some Ordinary Attr", required=False,
        default_value="", select_type="single",
        options=_menu("A", "B", "C"),
    )
    cond_attr = ConfigAttr(
        entity_id=2, variable_name="cond", display_label="Cond",
        required=False, default_value="", select_type="single",
        options=_menu("X"),
    )
    rec_rule = RecommendationRule(
        rule_name="Set someOrdinaryAttr_astro",
        condition_attr_id=2, condition_value="X", target_attr_id=1,
        conditions=[(2, "X", "4")], recommended_value="B",
    )
    eng = CpqEngine()
    filled = {"someOrdinaryAttr_astro": "A", "cond": "X"}
    filled_source = {"someOrdinaryAttr_astro": "user", "cond": "user"}

    ret_filled, _display, _pending = eng.auto_fill(
        [ordinary_attr, cond_attr], {}, already_filled=filled, filled_source=filled_source,
        constrained_opts={1: ["B", "C"]},
        rec_rules=[rec_rule],
    )

    assert ret_filled.get("someOrdinaryAttr_astro") == "B"


# ── Named allowlist extension (2026-08-18): 3 confirmed constraint-only ────
# attrs sharing accessoriesSolutionSet_astro's exact governance shape ───────

def test_related_service_category_selects_all_when_constrained_and_ambiguous():
    """relatedServiceCategory_astro: live-confirmed real constraint (script-
    backed rule 17691443159 + declarative rule 17691443165), zero
    recommendation rules -- now in _BLIND_FILL_RISK_ACCEPTED_VNS."""
    attr = ConfigAttr(
        entity_id=1, variable_name="relatedServiceCategory_astro",
        display_label="Service Category", required=False, default_value="",
        select_type="multi",
        options=_menu("DEVICE RENTAL", "DEVICE INSTALLATION", "DEVICE PROGRAMMING"),
    )
    eng = CpqEngine()
    filled_multi: dict = {}
    eng.auto_fill(
        [attr], {}, already_filled_multi=filled_multi,
        constrained_opts={1: ["DEVICE RENTAL", "DEVICE INSTALLATION"]},
        display_order={"relatedServiceCategory_astro": 0},
    )
    assert sorted(filled_multi.get("relatedServiceCategory_astro", [])) == [
        "DEVICE INSTALLATION", "DEVICE RENTAL",
    ]


def test_select_end_user_type_blind_picks_first_option_when_constrained():
    """selectEndUserType_astro: live-confirmed one real constraint rule,
    zero recommendation rules -- single-select, so the allowlist exception
    resolves via first-eligible-option, not select-all."""
    attr = ConfigAttr(
        entity_id=1, variable_name="selectEndUserType_astro",
        display_label="Select End User Type", required=False, default_value="",
        select_type="single",
        options=_menu("POLICE PROTECTION", "FIRE PROTECTION", "EMS"),
    )
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [attr], {}, governed_ids={1},
        constrained_opts={1: ["POLICE PROTECTION", "FIRE PROTECTION"]},
        display_order={"selectEndUserType_astro": 0},
    )
    assert filled.get("selectEndUserType_astro") == "POLICE PROTECTION"


def test_additional_system_enhancement_feature_type_still_stays_empty():
    """Regression guard: additionalSystemEnhancementFeatureType_astro (the
    documented "9-of-11, never guess" incident this whole check exists to
    prevent) is deliberately NOT in the allowlist -- must still stay
    empty, not select-all, even with the same constrained-ambiguous shape
    as the 3 newly-added attrs."""
    attr = ConfigAttr(
        entity_id=21, variable_name="additionalSystemEnhancementFeatureType_astro",
        display_label="Additional System Enhancement Feature Type",
        required=False, default_value="", select_type="multi",
        options=_menu(
            "DISABLE CLOUD SERVICES", "DELETE NARROWBANDING-WAIVER REQUIRED",
            "ICE KIT", "OPTIONAL EMERGENCY TONE", "SEQUENTIAL SERIAL NUMBER",
        ),
    )
    constrained_opts = {21: [
        "DISABLE CLOUD SERVICES", "ICE KIT", "OPTIONAL EMERGENCY TONE",
    ]}
    eng = CpqEngine()
    multi: dict = {}
    eng.auto_fill(
        [attr], hints={}, constrained_opts=constrained_opts,
        governed_ids={21}, rule_governed_ids={21}, already_filled_multi=multi,
        display_order={"additionalSystemEnhancementFeatureType_astro": 5},
    )
    assert multi.get("additionalSystemEnhancementFeatureType_astro") is None
