"""Grid quantities are seeded only for a selector the pass left pending (flag
`cpq_grid_quantity_pending_selectors_only_enabled`).

ws 1267, APX N30: auto-fill finished with 0 pending, then the grid step asked 7 quantity holders because their selectors
had no selection yet, although the selectors were never pending (the not-applicable guard had left them open)."""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.engine import CpqEngine
from tests.test_cpq_grid_quantity_asks_every_option_upfront_2026_08_25 import _grid_attrs

SELECTOR = "mountingTypeArray_viSoln"


def _append(pending, flag: bool, filled=None, filled_multi=None, selector_vns=None):
    attrs = _grid_attrs()
    chosen = [a for a in attrs if a.variable_name in pending]
    with patch("aryx.cpq.grid_quantity.append._pending_selectors_only", return_value=flag):
        out = CpqEngine().append_pending_grid_quantities(
            chosen, attrs, dict(filled or {}), dict(filled_multi or {}), selector_vns=selector_vns)
    return [a.variable_name for a in out]


def test_today_an_unpending_selector_is_seeded_as_quantity_questions():
    assert len(_append([], flag=False)) == 3


def test_with_the_flag_a_selector_the_pass_did_not_leave_pending_is_not_seeded():
    assert _append([], flag=True) == []


def test_a_pending_selector_is_still_replaced_by_its_per_option_questions():
    names = _append([SELECTOR], flag=True)
    assert SELECTOR not in names and len(names) == 3


def test_a_selector_with_a_selection_still_asks_its_selected_quantities():
    names = _append([], flag=True, filled_multi={SELECTOR: ["Locking Molle Mount"]})
    assert names == ["mountingTypeLockingMolleMountQuantity_viSoln"]


def test_a_caller_naming_one_selector_is_unchanged():
    assert len(_append([], flag=True, selector_vns={SELECTOR})) == 3


def test_the_selectors_the_flag_skips_are_logged_for_the_replay():
    with patch("aryx.cpq.grid_quantity.append.would_log", return_value=True), \
            patch("aryx.cpq.grid_quantity.append.raven_log") as log:
        _append([], flag=True)
    context = log.call_args.kwargs["context"]
    assert context["reason_code"] == "SELECTOR_NOT_PENDING" and context["skipped_selectors"] == [SELECTOR]
