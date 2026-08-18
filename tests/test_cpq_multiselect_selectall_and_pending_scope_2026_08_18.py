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
