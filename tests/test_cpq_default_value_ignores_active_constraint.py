"""auto_fill's raw XML default_value step must not lock in a value an
active constraint rule has already excluded.

Real incident (docs/config_consistency_issues_2026-07-30.md, Issue 7
follow-up): a brand-new, completely default APX NEXT Single Band order
failed its own BOM-gate stale-constraint check on the very first
confirm — every time, for every such order. Root cause: Carry Type's
catalog default_value ("2.0 INCH / 5.08 CM (STANDARD)") is genuinely
invalid under this product's own constraint rule ("Constrain for
APXNEXTSINGLE & APXNEXTXNSINGLE"), but auto_fill's default-value step
locked it in unconditionally, before the existing constraint-aware
fallback a few lines later (which already correctly picks a real, valid
option) ever got a chance to run. The customer had to answer a
stale-constraint reask for a value they never touched, on every single
default order.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def test_default_value_excluded_by_constraint_falls_through_to_valid_first_option():
    carry = ConfigAttr(
        entity_id=1, variable_name="beltClipType_astro", display_label="Carry Type",
        required=False, default_value="2.0 INCH / 5.08 CM (STANDARD)", select_type="single",
        options=_menu(
            "2.0 INCH / 5.08 CM (STANDARD)",  # catalog default — invalid for this product
            "PLASTIC HOLSTER WITH 2.5 INCH BELT CLIP (STANDARD)",  # first VALID option
            "3.0 INCH WITH HOLSTER",
            "NO CARRY SOLUTION",
        ),
    )
    eng = CpqEngine()
    # Active constraint (as apply_constraint_rules would compute it) excludes
    # the catalog default entirely.
    constrained_opts = {
        1: [
            "PLASTIC HOLSTER WITH 2.5 INCH BELT CLIP (STANDARD)",
            "3.0 INCH WITH HOLSTER",
            "NO CARRY SOLUTION",
        ],
    }

    filled, display_filled, pending = eng.auto_fill(
        [carry], hints={}, constrained_opts=constrained_opts,
        governed_ids={1}, rule_governed_ids={1},
    )

    assert filled.get("beltClipType_astro") == "PLASTIC HOLSTER WITH 2.5 INCH BELT CLIP (STANDARD)", (
        "the catalog's own default_value must never be locked in once an "
        "active constraint has already excluded it — the attr should fall "
        "through to the first VALID option instead, not the customer "
        "having to correct a value they never touched"
    )
    assert display_filled.get("beltClipType_astro") == "PLASTIC HOLSTER WITH 2.5 INCH BELT CLIP (STANDARD)"
    assert pending == []


def test_default_value_still_wins_when_constraint_allows_it():
    """The fix must not change behavior for the common case — a default
    that IS in the active constraint's allowed set still wins outright,
    no unnecessary fall-through."""
    carry = ConfigAttr(
        entity_id=1, variable_name="beltClipType_astro", display_label="Carry Type",
        required=False, default_value="NO CARRY SOLUTION", select_type="single",
        options=_menu("NO CARRY SOLUTION", "3.0 INCH WITH HOLSTER"),
    )
    eng = CpqEngine()
    constrained_opts = {1: ["NO CARRY SOLUTION", "3.0 INCH WITH HOLSTER"]}

    filled, _display, _pending = eng.auto_fill(
        [carry], hints={}, constrained_opts=constrained_opts,
        governed_ids={1}, rule_governed_ids={1},
    )

    assert filled.get("beltClipType_astro") == "NO CARRY SOLUTION"


def test_default_value_unaffected_when_no_constraint_is_active():
    """No entry for this attr in constrained_opts at all (the common
    case — no active constraint rule) must behave exactly as before: the
    catalog default wins."""
    carry = ConfigAttr(
        entity_id=1, variable_name="beltClipType_astro", display_label="Carry Type",
        required=False, default_value="2.0 INCH / 5.08 CM (STANDARD)", select_type="single",
        options=_menu("2.0 INCH / 5.08 CM (STANDARD)", "3.0 INCH WITH HOLSTER"),
    )
    eng = CpqEngine()

    filled, _display, _pending = eng.auto_fill([carry], hints={})

    assert filled.get("beltClipType_astro") == "2.0 INCH / 5.08 CM (STANDARD)"


def test_ungoverned_attr_with_excluded_default_asks_instead_of_guessing():
    """An attr excluded by a constraint but with NO governing rule at all
    must fall through to pending (ask), not silently guess — same "never
    guess" discipline as everywhere else in this engine."""
    other = ConfigAttr(
        entity_id=1, variable_name="someUngovernedAttr_astro", display_label="Some Attribute",
        required=False, default_value="A", select_type="single",
        options=_menu("A", "B", "C"),
    )
    eng = CpqEngine()
    constrained_opts = {1: ["B", "C"]}

    filled, _display, pending = eng.auto_fill(
        [other], hints={}, constrained_opts=constrained_opts,
    )

    assert filled.get("someUngovernedAttr_astro") is None
    assert any(a.variable_name == "someUngovernedAttr_astro" for a in pending)
