"""extract_catalog_hints: an option text owned by several attrs selects the
product selector (productSelectionProduct_all) when it is one of the owners.

Live case (2026-10-07, ws 1267, Astro25Configdata, probed on the real 3,172
attrs): "APX 900" is the only "APX 900" option of productSelectionProduct_all
(code APX900FLASHPORT) and also an option of productSelectionDMSO_astro (the
DMS service picker, code APX900). The 2-owner never-guess rule hinted nothing,
so Product was asked with ~300 options.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption

PRODUCT = "productSelectionProduct_all"
DMS = "productSelectionDMSO_astro"


def _attr(vn: str, pairs: list[tuple[str, str]], select_type: str = "single") -> ConfigAttr:
    return ConfigAttr(
        entity_id=hash(vn) % 10_000, variable_name=vn, display_label=vn,
        required=False, default_value="", select_type=select_type,
        options=[MenuOption(item_value=iv, display_name=dn, order=i)
                 for i, (iv, dn) in enumerate(pairs, start=1)],
    )


def _real_shape() -> list[ConfigAttr]:
    return [
        _attr(PRODUCT, [("APX900FLASHPORT", "APX 900"), ("APX6500", "APX 6500"), ("APX6500LI", "APX 6500Li")]),
        _attr(DMS, [("APX900", "APX 900"), ("APX6500", "APX 6500")]),
        _attr("modelsDMSStandAlone_astro", [("APX900", "APX900")], select_type="multi"),
    ]


def _hints(question: str, attrs: list[ConfigAttr]) -> dict[str, str]:
    return CpqEngine().extract_catalog_hints(question, attrs)[0]


def test_product_selector_wins_a_multi_owner_phrase():
    assert _hints("I want a quote for APX 900", _real_shape()) == {PRODUCT: "APX900FLASHPORT"}


def test_other_owner_is_not_hinted():
    assert DMS not in _hints("I want a quote for APX 6500", _real_shape())
    assert _hints("I want a quote for APX 6500", _real_shape()) == {PRODUCT: "APX6500"}


def test_multi_owner_without_the_product_selector_still_never_guesses():
    attrs = [_attr("carrierA_astro", [("ATT", "AT&T FirstNet")]),
             _attr("carrierB_astro", [("ATT", "AT&T FirstNet")])]
    assert _hints("we need AT&T FirstNet", attrs) == {}


def test_product_selector_with_two_values_for_the_phrase_still_asks():
    attrs = [_attr(PRODUCT, [("APX900", "APX 900"), ("APX900FLASHPORT", "APX 900")]),
             _attr(DMS, [("APX900", "APX 900")])]
    assert _hints("I want a quote for APX 900", attrs) == {}


def test_single_owner_unchanged():
    attrs = [_attr(PRODUCT, [("APX6500", "APX 6500")])]
    assert _hints("APX 6500 please", attrs) == {PRODUCT: "APX6500"}


def test_negated_mention_is_not_a_selection():
    assert PRODUCT not in _hints("exclude the APX 900 for now", _real_shape())


def test_hidden_product_selector_is_not_hinted():
    attrs = _real_shape()
    attrs[0].hidden = True
    assert PRODUCT not in _hints("I want a quote for APX 900", attrs)
