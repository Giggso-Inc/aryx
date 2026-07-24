"""Regression test: a cascade-invalidated, previously USER-ANSWERED attr
must be re-asked (added to `pending`), not silently re-guessed by the
governed blind-fallback branch (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 4).

Root cause traced: once a constraint re-narrows an already-filled attr's
allowed set, `auto_fill` clears the stale value and falls through to normal
resolution on the SAME turn. If the attr is rule-governed with 2+ remaining
valid options, the blind-fallback branch used to silently pick a new value
(first-by-order or a rule recommendation) instead of asking — even when the
value it just cleared was a real customer decision (filled_source=="user").
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _attr(entity_id, vn, options):
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=vn,
        required=False, default_value="", options=options,
    )


def test_cascade_dropped_user_answer_is_re_asked_not_reguessed():
    eng = CpqEngine()
    # 3 options so the constraint still leaves 2+ valid — the exactly-one-
    # remaining-choice shortcut (a separate, correct auto-fill path) must
    # NOT be what's exercised here; this targets the blind-fallback branch.
    attr = _attr(1, "serviceType_viSoln", [
        MenuOption("TECH_SUPPORT", "Tech Support and Hardware Repair", 1),
        MenuOption("STANDARD_WARRANTY", "1 Year Standard Warranty Only", 2),
        MenuOption("EXTENDED_WARRANTY", "Extended Warranty", 3),
    ])
    filled, display_filled, pending = eng.auto_fill(
        attrs=[attr], hints={},
        already_filled={"serviceType_viSoln": "TECH_SUPPORT"},
        filled_source={"serviceType_viSoln": "user"},
        constrained_opts={1: ["STANDARD_WARRANTY", "EXTENDED_WARRANTY"]},
        governed_ids={1}, rule_governed_ids={1},
    )
    assert "serviceType_viSoln" not in filled, (
        "the invalidated user answer must not survive re-validation")
    assert any(a.variable_name == "serviceType_viSoln" for a in pending), (
        "a cascade-cleared USER decision must be re-asked, not silently "
        "re-filled with a new guessed value"
    )


def test_cascade_dropped_non_user_value_still_blind_fills_as_before():
    # Control case: an auto-filled (non-"user") value that gets cleared by
    # the same re-validation keeps the EXISTING blind-fallback behavior —
    # this fix only changes the outcome for real user decisions.
    eng = CpqEngine()
    attr = _attr(1, "serviceType_viSoln", [
        MenuOption("TECH_SUPPORT", "Tech Support and Hardware Repair", 1),
        MenuOption("STANDARD_WARRANTY", "1 Year Standard Warranty Only", 2),
        MenuOption("EXTENDED_WARRANTY", "Extended Warranty", 3),
    ])
    filled, display_filled, pending = eng.auto_fill(
        attrs=[attr], hints={},
        already_filled={"serviceType_viSoln": "TECH_SUPPORT"},
        filled_source={"serviceType_viSoln": "default"},
        constrained_opts={1: ["STANDARD_WARRANTY", "EXTENDED_WARRANTY"]},
        governed_ids={1}, rule_governed_ids={1},
    )
    assert filled.get("serviceType_viSoln") == "STANDARD_WARRANTY"
    assert not any(a.variable_name == "serviceType_viSoln" for a in pending)
