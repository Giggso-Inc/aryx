"""extract_catalog_hints end to end: a shared option label still produces a hint.

Companion to test_cpq_catalog_hint_shared_label_tie_2026_10_07.py, which tests
the tie rule in isolation. This one goes through the real engine entry point so
the WIRING is covered too -- the defect it guards was not in the rule but in
the caller, which skipped every phrase owned by 2+ values before any tie-break
could run.

Live shape (ws 1267, 2026-10-07): the product selector holds two options with
the same display text, one storing the product's own code and one storing a
variant's. Asking for the product hinted nothing, the model leaf stayed
ambiguous, and the reply listed all 132 products in the family.

Values below are generic, not real catalog codes.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption

PRODUCT_VN = "productSelectionProduct_all"


def _attr(vn: str, pairs: list[tuple[str, str]], select_type: str = "single") -> ConfigAttr:
    """Build a ConfigAttr from (item_value, display_name) pairs."""
    return ConfigAttr(
        entity_id=hash(vn) % 10_000, variable_name=vn, display_label=vn,
        required=False, default_value="", select_type=select_type,
        options=[MenuOption(item_value=iv, display_name=dn, order=i)
                 for i, (iv, dn) in enumerate(pairs, start=1)],
    )


# Two options sharing one label, plus unrelated siblings for noise.
_SHARED_LABEL = [
    ("THINGONE", "Thing One"),
    ("THINGONEVARIANT", "Thing One"),
    ("THINGTWO", "Thing Two"),
    ("THINGTWOLITE", "Thing Two Lite"),
]


def _hints(question: str, attrs: list[ConfigAttr]) -> dict[str, str]:
    hints, _negated = CpqEngine().extract_catalog_hints(question, attrs)
    return hints


def test_shared_label_now_hints_the_plain_code():
    attrs = [_attr(PRODUCT_VN, _SHARED_LABEL)]
    assert _hints("i want a quote for thing one for us", attrs) == {PRODUCT_VN: "THINGONE"}


def test_unshared_label_is_unaffected():
    attrs = [_attr(PRODUCT_VN, _SHARED_LABEL)]
    assert _hints("i want a quote for thing two lite", attrs) == {PRODUCT_VN: "THINGTWOLITE"}


def test_shared_label_with_no_exact_code_still_hints_nothing():
    attrs = [_attr(PRODUCT_VN, [
        ("THING ONE MULTI", "Thing One All Band"),
        ("THINGONEXVARIANT", "Thing One All Band"),
    ])]
    assert _hints("i want a quote for thing one all band", attrs) == {}


def test_nothing_mentioned_hints_nothing():
    attrs = [_attr(PRODUCT_VN, _SHARED_LABEL)]
    assert _hints("hello, can you help me with a quote", attrs) == {}
