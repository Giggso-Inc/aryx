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
