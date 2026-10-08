"""Regression test for the stale-blind-pick-lock bug found live on
workspace 1267 (APX 900, 2026-10-08): `beltClipType_astro` got blind-picked
"COVERT CARRY HOLSTER" (source "blind_pick_rule_governed") on an early pass,
before Base Model was known -- then `cpq_defaultinattr_shape_enabled`'s real
Defaultinattr default for the resolved base model could never apply, because
`stage_already_filled`'s re-open gate only recognized the literal source tag
"default_first_available", not "blind_pick_rule_governed" (or its sibling,
"blind_pick_governed" from `ask_data_gap.py`) -- both are the exact same
"guessed, not known" category `derive_base_model_pick.blind_attrs()` already
treats identically via `_BLIND_SOURCE_PREFIXES`.

Same technique as `test_cpq_rule_loop_perf_gating_2026_08_19.py`'s
`default_first_available` tests: a sentinel value that could never arise
from a genuine derivation proves whether the gate skipped or allowed
re-derivation.
"""
from __future__ import annotations

import pytest

from aryx.cpq.engine import CpqEngine, _fill_signature
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _attr(vn: str, *values: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name=vn, display_label=vn, required=False,
        default_value="", select_type="single", options=_menu(*values),
    )


@pytest.mark.parametrize("blind_source", ["blind_pick_rule_governed", "blind_pick_governed"])
def test_blind_pick_governed_singleselect_rederives_when_signature_changes(blind_source):
    """The actual bug: a mismatched signature (representing "Base Model is
    now known, context has genuinely changed since this guess") must let
    real re-derivation run for these source tags too, not just the literal
    "default_first_available" one."""
    attr = _attr("x", "A", "B", "C")
    eng = CpqEngine()
    filled = {"x": "__SENTINEL_NEVER_A_REAL_OPTION__"}
    sources = {"x": blind_source}
    sigs = {"x": _fill_signature({}, {}, set())}  # deliberately mismatched

    filled, _display, _ = eng.auto_fill(
        [attr], hints={}, already_filled=filled, filled_source=sources,
        constrained_opts=None, governed_ids={1}, rule_governed_ids={1},
        display_order={"x": 0}, _default_fill_signatures=sigs,
    )
    assert filled["x"] == "A", (
        f"a changed signature must allow real re-derivation to run for "
        f"source {blind_source!r}, the same as it already does for "
        f"'default_first_available'"
    )


@pytest.mark.parametrize("blind_source", ["blind_pick_rule_governed", "blind_pick_governed"])
def test_blind_pick_governed_singleselect_not_rederived_when_signature_unchanged(blind_source):
    """Positive control: the gate must still SKIP re-derivation when nothing
    relevant has changed -- confirms the fix doesn't regress the perf gate
    itself, it only widens which source tags it applies to."""
    attr = _attr("x", "A", "B", "C")
    eng = CpqEngine()
    filled = {"x": "__SENTINEL_NEVER_A_REAL_OPTION__"}
    sources = {"x": blind_source}
    sigs = {"x": _fill_signature(filled, {}, {1})}

    returned_filled, _display, _ = eng.auto_fill(
        [attr], hints={}, already_filled=filled, filled_source=sources,
        constrained_opts=None, governed_ids={1}, rule_governed_ids={1},
        display_order={"x": 0}, _default_fill_signatures=sigs,
    )
    assert filled["x"] == "__SENTINEL_NEVER_A_REAL_OPTION__"
    assert returned_filled.get("x") == "__SENTINEL_NEVER_A_REAL_OPTION__"


def _attr_id(entity_id: int, vn: str, *values: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=vn, required=False,
        default_value="", select_type="single", options=_menu(*values),
    )


SENTINEL = "__SENTINEL_NEVER_A_REAL_OPTION__"


def _auto_fill(attrs, filled, sources, sigs, constrained_opts=None):
    return CpqEngine().auto_fill(
        attrs, hints={}, already_filled=filled, filled_source=sources,
        constrained_opts=constrained_opts, governed_ids={a.entity_id for a in attrs},
        rule_governed_ids={a.entity_id for a in attrs}, display_order={a.variable_name: i for i, a in enumerate(attrs)},
        _default_fill_signatures=sigs,
    )


@pytest.mark.parametrize("blind_source", ["blind_pick_rule_governed", "blind_pick_governed"])
def test_the_signature_is_recorded_lazily_at_the_first_revisit_and_then_gates(blind_source):
    """Production starts a turn with an EMPTY signature dict: the first revisit re-derives and records the
    signature, the next identical state is kept. Nothing here presets a signature by hand."""
    attr = _attr("x", "A", "B", "C")
    sigs: dict = {}
    filled, _display, _ = _auto_fill([attr], {"x": SENTINEL}, {"x": blind_source}, sigs)
    assert filled["x"] == "A" and "x" in sigs                   # first revisit: re-derived, signature recorded

    again, _display, _ = _auto_fill([attr], {"x": SENTINEL}, {"x": blind_source}, sigs)
    assert again["x"] == SENTINEL                               # identical state: the gate keeps the value


def test_a_customer_answer_is_never_reopened_whatever_the_signature():
    """Negative control: a "user"-sourced value stays locked even with an empty or mismatched signature."""
    attr = _attr("x", "A", "B", "C")
    for sigs in ({}, {"x": _fill_signature({}, {}, set())}):
        filled, _display, _ = _auto_fill([attr], {"x": SENTINEL}, {"x": "user"}, sigs)
        assert filled["x"] == SENTINEL


@pytest.mark.parametrize("blind_source", ["blind_pick_rule_governed", "blind_pick_governed"])
def test_a_blind_pick_made_before_the_context_is_known_yields_to_the_real_value_once_it_is(blind_source):
    """The live scenario (APX 900, belt clip): an early blind pick, then a later pass in which another attribute
    (the base model) is known and a better-informed value for x is available. The stand-in for that value is a hint
    for B: the value A is still a legal option, so only the re-open gate (not a constraint dropping A) can let B win."""
    attr_x = _attr_id(1, "x", "A", "B", "C")
    attr_base = _attr_id(2, "base", "H1", "H2")
    sigs = {"x": _fill_signature({"x": "A"}, {}, {1, 2})}      # recorded for the pass-1 state (only x filled)
    filled, _display, _ = CpqEngine().auto_fill(
        [attr_x, attr_base], hints={"x": "B"}, already_filled={"x": "A", "base": "H1"},
        filled_source={"x": blind_source, "base": "user"}, constrained_opts=None,
        governed_ids={1, 2}, rule_governed_ids={1, 2}, _default_fill_signatures=sigs,
    )
    assert filled["x"] == "B"                                   # the guess yielded to the better-informed value
    assert filled["base"] == "H1"                               # the customer's answer is untouched


@pytest.mark.parametrize("blind_source", ["blind_pick_rule_governed", "blind_pick_governed"])
def test_the_same_pass_keeps_the_blind_pick_when_nothing_changed(blind_source):
    """Control for the test above: with the pass-1 state unchanged the hint cannot re-open the guess."""
    attr_x = _attr_id(1, "x", "A", "B", "C")
    sigs = {"x": _fill_signature({"x": "A"}, {}, {1})}
    filled, _display, _ = CpqEngine().auto_fill(
        [attr_x], hints={"x": "B"}, already_filled={"x": "A"}, filled_source={"x": blind_source},
        constrained_opts=None, governed_ids={1}, rule_governed_ids={1}, _default_fill_signatures=sigs,
    )
    assert filled["x"] == "A"


def test_the_rederive_reason_code_tells_the_sources_apart():
    from aryx.cpq.auto_fill_stages import tier0_already_filled as stage
    from unittest.mock import patch

    attr = _attr("x", "A", "B", "C")
    seen: list[str] = []
    with patch.object(stage.fill_log, "log_pruned", side_effect=lambda vn, reason, *a, **k: seen.append(reason)):
        _auto_fill([attr], {"x": SENTINEL}, {"x": "default_first_available"}, {})
        _auto_fill([attr], {"x": SENTINEL}, {"x": "blind_pick_rule_governed"}, {})
    assert seen == ["DEFAULT_FIRST_AVAILABLE_REDERIVE", "BLIND_PICK_REDERIVE"]
