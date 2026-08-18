"""docs/CPQ_DATA_GAP_SKIP_AND_RULE_GOVERNED_BLIND_PICK_PLAN_2026_08_10.md

Two policy changes to auto_fill's final pending-decision fallback, HITL-
confirmed via /andie 2026-08-10:

Group 1 -- an attr whose only real governance is a hiding rule that can
never resolve (depends on a data table confirmed absent from every ingested
catalog, e.g. UserGroupMapping) is warned-and-skipped instead of asked
forever.

Group 2 -- an attr with real recommendation/constraint/hiding rules, none of
which fire for the current state, and NO default_value at all, blind-picks
the first rule-valid option instead of asking. Three pre-existing safety
nets must still override this: _NEVER_GUESS_SCRIPT_GOVERNED (a curated
allowlist of attrs already confirmed broken by blind-picking), a cascade
that just invalidated the customer's own prior answer (user_answered_
dropped_ids -- must re-ask, never reguess), and a real default_value that
simply didn't survive an active constraint (structurally different from "no
default at all" -- stays unfilled).

Both new branches only run once auto_fill's EARLIER "is_governed and
valid_opts" default-first-available fallback (the pre-existing §2f/§2g
machinery, ~line 6614) has already declined to claim the attr -- which,
per apply_constraint_rules' own contract, happens when `constrained_opts`
is a real non-empty dict (some OTHER attr had an active constraint fire
this turn) but THIS attr's own entity_id isn't a key in it. All tests below
use `constrained_opts={999: [...]}` (an unrelated id) to reproduce that
exact real-world shape rather than passing no constrained_opts at all
(which would let the earlier §2f/§2g branch claim the attr first).
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, HidingRule, MenuOption

_UNRELATED_CONSTRAINED_OPTS = {999: ["Z"]}


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _attr(entity_id: int, vn: str, default_value: str = "") -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=vn,
        required=False, default_value=default_value, select_type="single",
        options=_menu("A", "B"), source_id=entity_id,
    )


def _attr_with_distinct_source_id(entity_id: int, source_id: int, vn: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=vn,
        required=False, default_value="", select_type="single",
        options=_menu("A", "B"), source_id=source_id,
    )


# ── Group 1: missing-data-table skip ────────────────────────────────────────

def test_attr_matched_via_source_id_not_entity_id_is_skipped(caplog):
    # Confirmed live (workspace 39005): the real hiding rule's
    # target_attr_id is the BM-native source_id (e.g. 18302531462), not the
    # FalkorDB graph entity_id (e.g. 292414) -- this is the exact real-world
    # shape that silently defeated an entity_id-only check.
    attr = _attr_with_distinct_source_id(292414, 18302531462, "cBPQRCode_astro")
    rule = HidingRule(
        rule_name="Hide unless part of APXRADIOs9YRS customer group",
        target_attr_id=18302531462, condition_attr_id=0, condition_value="",
        hide=True,
        script='bmql("select id_name from UserGroupMapping where group_name = \'APXRADIOS9YRS\'")',
    )
    eng = CpqEngine()
    import logging
    with caplog.at_level(logging.WARNING):
        filled, _display, pending = eng.auto_fill(
            [attr], {}, governed_ids={292414}, rule_governed_ids={292414},
            hiding_rules=[rule], display_order={"cBPQRCode_astro": 36},
            constrained_opts=_UNRELATED_CONSTRAINED_OPTS,
        )
    assert "cBPQRCode_astro" not in filled
    assert not any(a.variable_name == "cBPQRCode_astro" for a in pending)
    assert any("UserGroupMapping" in r.message for r in caplog.records)


def test_attr_blocked_on_missing_data_table_is_skipped_not_asked(caplog):
    attr = _attr(1, "cBPQRCode_astro")
    rule = HidingRule(
        rule_name="Hide unless part of APXRADIOs9YRS customer group",
        target_attr_id=1, condition_attr_id=0, condition_value="", hide=True,
        script='bmql("select id_name from UserGroupMapping where group_name = \'APXRADIOS9YRS\'")',
    )
    eng = CpqEngine()
    import logging
    with caplog.at_level(logging.WARNING):
        filled, _display, pending = eng.auto_fill(
            [attr], {}, governed_ids={1}, rule_governed_ids={1},
            hiding_rules=[rule], display_order={"cBPQRCode_astro": 36},
            constrained_opts=_UNRELATED_CONSTRAINED_OPTS,
        )
    assert "cBPQRCode_astro" not in filled
    assert not any(a.variable_name == "cBPQRCode_astro" for a in pending)
    assert any("UserGroupMapping" in r.message for r in caplog.records)


def test_hiding_rule_referencing_unregistered_table_is_unaffected():
    attr = _attr(1, "someOtherAttr_astro")
    rule = HidingRule(
        rule_name="Hide unless in SomeOtherTable",
        target_attr_id=1, condition_attr_id=0, condition_value="", hide=True,
        script='bmql("select id_name from SomeOtherTable where x = 1")',
    )
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill(
        [attr], {}, governed_ids={1}, rule_governed_ids={1},
        hiding_rules=[rule], display_order={"someOtherAttr_astro": 1},
        constrained_opts=_UNRELATED_CONSTRAINED_OPTS,
    )
    # Not in the known-missing-tables registry -- falls through to Group 2's
    # blind-pick (real rule governance, no default) rather than being
    # skipped by Group 1's mechanism specifically.
    assert filled.get("someOtherAttr_astro") == "A"


def test_hiding_rules_none_is_a_complete_noop():
    attr = _attr(1, "cBPQRCode_astro")
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill(
        [attr], {}, governed_ids={1}, rule_governed_ids={1},
        display_order={"cBPQRCode_astro": 36},
        constrained_opts=_UNRELATED_CONSTRAINED_OPTS,
    )
    # No hiding_rules passed at all -- Group 1 can't fire, falls through to
    # Group 2's blind-pick (still real rule governance, no default).
    assert filled.get("cBPQRCode_astro") == "A"


# ── Group 2: rule-governed blind-pick ───────────────────────────────────────

def test_rule_governed_attr_with_no_default_blind_picks_first_valid_option():
    attr = _attr(1, "wirelessCarrier_astro")
    eng = CpqEngine()
    filled, display_filled, pending = eng.auto_fill(
        [attr], {}, governed_ids={1}, rule_governed_ids={1},
        display_order={"wirelessCarrier_astro": 60},
        constrained_opts=_UNRELATED_CONSTRAINED_OPTS,
    )
    assert filled.get("wirelessCarrier_astro") == "A"
    assert display_filled.get("wirelessCarrier_astro") == "A"
    assert not pending


def test_rule_governed_attr_with_real_default_value_is_not_blind_picked():
    # Structurally distinct from "no default at all" -- a real
    # default_value stops Group 2 from firing at all, matching test_
    # default_value_not_used_when_it_does_not_survive_the_constraint's
    # existing, deliberate scoping for the sibling §2g/§2f machinery.
    attr = _attr(1, "wirelessCarrier_astro", default_value="A")
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [attr], {}, governed_ids={1}, rule_governed_ids={1},
        display_order={"wirelessCarrier_astro": 60},
        constrained_opts=_UNRELATED_CONSTRAINED_OPTS,
    )
    assert "wirelessCarrier_astro" not in filled


def test_never_guess_allowlisted_attr_is_not_blind_picked_by_group_2():
    attr = _attr(1, "wouldYouLikeToIncludeABatterySubscription_viSoln")
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill(
        [attr], {}, governed_ids={1}, rule_governed_ids={1},
        constrained_opts=_UNRELATED_CONSTRAINED_OPTS,
    )
    assert "wouldYouLikeToIncludeABatterySubscription_viSoln" not in filled
    assert any(
        a.variable_name == "wouldYouLikeToIncludeABatterySubscription_viSoln"
        for a in pending
    )


def test_attr_with_zero_rule_governance_still_reaches_pending():
    attr = _attr(1, "trulyUngovernedAttr_astro")
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill(
        [attr], {}, governed_ids=set(), rule_governed_ids=set(),
        constrained_opts=_UNRELATED_CONSTRAINED_OPTS,
    )
    assert "trulyUngovernedAttr_astro" not in filled
    assert any(a.variable_name == "trulyUngovernedAttr_astro" for a in pending)
