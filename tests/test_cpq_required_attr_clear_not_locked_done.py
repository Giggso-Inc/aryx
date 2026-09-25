"""stage_already_filled's "deliberately cleared" shortcut (D4, docs/CPQ_
POST_QUOTE_EDIT_AND_QA_PLAN.md) must not apply to a REQUIRED attribute --
CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T7.

Before this fix, an already-filled=="" + filled_source="user" single-select
was marked done regardless of attr.required, but bom_gate_required.py's
find_missing_required_fields() correctly still flags an empty required attr
as missing -- tier0 said "done", the gate said "incomplete". detect_attr_
clear() (tests/test_cpq_post_approval_activation.py::test_u10) already
refuses to let a customer CLEAR a required attr in the first place, which
is the same "required attrs can't be left intentionally blank" rule this
fix makes tier0 honor too, closing the one path that skipped it.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _attr(required: bool) -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name="someAttr_astro", display_label="Some Attr",
        required=required, default_value="", select_type="single",
        options=[
            MenuOption(item_value="A", display_name="A", order=1),
            MenuOption(item_value="B", display_name="B", order=2),
        ],
    )


def test_optional_attr_user_clear_stays_settled_as_none():
    """Regression guard: the existing, intended behavior for an OPTIONAL
    attr is unchanged by this fix."""
    engine = CpqEngine()
    filled, display, pending = engine.auto_fill(
        [_attr(required=False)], hints={},
        already_filled={"someAttr_astro": ""},
        filled_source={"someAttr_astro": "user"},
    )
    assert "someAttr_astro" not in pending
    assert filled.get("someAttr_astro") == ""
    assert display.get("someAttr_astro") == "(none)"


def test_required_attr_user_clear_is_not_locked_done():
    """The fix: a REQUIRED attr's "" + source=user must NOT be treated as
    a settled, permanent decision -- the BOM gate will reject it as missing
    regardless, so locking it as "done" here only hides the problem from
    the customer instead of re-asking."""
    engine = CpqEngine()
    filled, display, pending = engine.auto_fill(
        [_attr(required=True)], hints={},
        already_filled={"someAttr_astro": ""},
        filled_source={"someAttr_astro": "user"},
    )
    assert display.get("someAttr_astro") != "(none)", (
        "a required attr's clear must not be silently accepted as a "
        "settled '(none)' answer the way an optional attr's is"
    )


def test_required_attr_user_clear_is_actually_re_asked():
    """T7 follow-up (real-data testing against workspace 704,
    2026-09-25): the assertion above only checked the display label --
    it passed even though the attribute was silently kept "done" and
    never re-entered `pending` (confirmed live with a real required
    attribute, _BM_USER_CURRENCY: state.done stayed True, pending stayed
    empty). Not showing "(none)" is not the same as actually re-asking --
    this is the behavior the original fix's own docstring claimed
    ("falls through to normal re-resolution/re-ask") but never verified."""
    engine = CpqEngine()
    filled, display, pending = engine.auto_fill(
        [_attr(required=True)], hints={},
        already_filled={"someAttr_astro": ""},
        filled_source={"someAttr_astro": "user"},
    )
    assert "someAttr_astro" not in filled, "cleared required attr must not stay locked in as filled"
    assert any(a.variable_name == "someAttr_astro" for a in pending), (
        "a required attr's clear must actually re-enter pending so the "
        "customer is re-asked, not just displayed differently"
    )
