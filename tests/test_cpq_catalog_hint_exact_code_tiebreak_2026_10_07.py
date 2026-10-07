"""extract_catalog_hints: a label shared by several values of one attr is
resolved when exactly one value's own code IS the typed phrase.

Live case (2026-10-07, ws 1267, Astro25Configdata): productSelectionProduct_all
has APX900 and APX900FLASHPORT both displayed as "APX 900". "I want a quote
for APX 900" hinted nothing, so Product was asked with ~300 options.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _attr(vn: str, pairs: list[tuple[str, str]], select_type: str = "single") -> ConfigAttr:
    return ConfigAttr(
        entity_id=hash(vn) % 10_000, variable_name=vn, display_label=vn,
        required=False, default_value="", select_type=select_type,
        options=[MenuOption(item_value=iv, display_name=dn, order=i)
                 for i, (iv, dn) in enumerate(pairs, start=1)],
    )


_PRODUCT = [("APX900", "APX 900"), ("APX900FLASHPORT", "APX 900"),
            ("APX6500", "APX 6500"), ("APX6500LI", "APX 6500Li")]


def _hints(question: str, attrs: list[ConfigAttr]) -> dict[str, str]:
    hints, _neg = CpqEngine().extract_catalog_hints(question, attrs)
    return hints


def test_shared_label_resolves_to_the_value_whose_code_is_typed():
    attr = _attr("productSelectionProduct_all", _PRODUCT)
    assert _hints("I want a quote for APX 900", [attr]) == {"productSelectionProduct_all": "APX900"}
    assert _hints("quote apx900 please", [attr]) == {"productSelectionProduct_all": "APX900"}


def test_variant_named_explicitly_still_wins():
    attr = _attr("productSelectionProduct_all", _PRODUCT)
    assert _hints("I want an APX900FLASHPORT", [attr]) == {"productSelectionProduct_all": "APX900FLASHPORT"}


def test_no_value_whose_code_is_the_phrase_still_asks():
    """Parenthetical-suffix tie (existing N04 guard): neither code equals the phrase."""
    attr = _attr("hWVersion_astro", [
        ("NEXT ENHANCED LTE PLUS 5G", "APX NEXT (4G LTE+5G)"),
        ("XE ENHANCED LTE PLUS 5G", "APX NEXT XE (4G LTE+5G)"),
    ])
    assert _hints("I'll take the 4G LTE+5G version", [attr]) == {}


def test_two_values_with_the_same_normalized_code_still_ask():
    attr = _attr("productSelectionProduct_all", [("APX-900", "APX 900"), ("APX 900", "APX 900 Kit")])
    assert _hints("I want a quote for APX 900", [attr]) == {}


def test_label_shared_across_different_attrs_is_unchanged():
    """2+ owning attrs is a different guard; the tie-break never runs."""
    a = _attr("productSelectionProduct_all", [("APX900", "APX 900")])
    b = _attr("spareRadioModel_astro", [("APX900", "APX 900")])
    assert _hints("I want a quote for APX 900", [a, b]) == {}


def test_negated_mention_is_still_not_a_selection():
    attr = _attr("productSelectionProduct_all", _PRODUCT)
    assert "productSelectionProduct_all" not in _hints("exclude the APX 900 for now", [attr])
