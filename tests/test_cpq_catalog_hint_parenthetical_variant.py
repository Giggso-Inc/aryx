"""Regression coverage: N04 (cpq_test_cases.xlsx, 7-Negation).

extract_catalog_hints' D2 verbatim rule requires the WHOLE glued option
text (item_value or display_name) to appear in the question. Real catalog
data (APX_next.xml, hWVersion_astro) shows display names shaped like
"APX NEXT (4G LTE+5G)" — a common family name outside the parens, the
specific variant inside. "I'll take the 4G LTE+5G version" — the most
natural way to answer, naming only the distinguishing part — never
satisfied the whole-string rule and silently yielded nothing.

Fix: _parenthetical_suffix (plain string parsing, no pattern list, no
per-product special-casing) exposes the inner segment as an additional
candidate text alongside item_value/display_name, so it flows through the
exact same ambiguity/negation/never-guess machinery as every other
candidate. Also strengthens the ambiguity guard from "2+ different attrs
share this phrase" to "2+ different real values (same attr or not) share
this phrase" — real catalog data shows sibling hardware-version options on
DIFFERENT products can carry the identical variant suffix (both "APX NEXT"
and "APX NEXT XE" have a "(4G LTE+5G)" option), which the old owners-only
check would not have caught once the parenthetical text becomes a
candidate too.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine, _parenthetical_suffix
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(pairs: list[tuple[str, str]]) -> list[MenuOption]:
    return [
        MenuOption(item_value=iv, display_name=dn, order=i)
        for i, (iv, dn) in enumerate(pairs, start=1)
    ]


def test_variant_only_answer_resolves_via_the_parenthetical_suffix():
    """N04: real hWVersion_astro shape from APX_next.xml."""
    attr = ConfigAttr(
        entity_id=1, variable_name="hWVersion_astro", display_label="Hardware Version",
        required=False, default_value="", select_type="single",
        options=_menu([
            ("NEXT ENHANCED LTE PLUS 5G", "APX NEXT (4G LTE+5G)"),
            ("NEXT STANDARD LTE ONLY", "APX NEXT (4G LTE Only)"),
        ]),
    )
    eng = CpqEngine()
    hints, _negated = eng.extract_catalog_hints(
        "I'll take the 4G LTE+5G version", [attr],
    )
    assert hints == {"hWVersion_astro": "NEXT ENHANCED LTE PLUS 5G"}


def test_full_verbatim_display_name_still_matches_unchanged():
    """N01 — must not regress the existing whole-string match."""
    attr = ConfigAttr(
        entity_id=1, variable_name="hWVersion_astro", display_label="Hardware Version",
        required=False, default_value="", select_type="single",
        options=_menu([("NEXT ENHANCED LTE PLUS 5G", "APX NEXT (4G LTE+5G)")]),
    )
    eng = CpqEngine()
    hints, _negated = eng.extract_catalog_hints(
        "I'll take the APX NEXT (4G LTE+5G) version", [attr],
    )
    assert hints == {"hWVersion_astro": "NEXT ENHANCED LTE PLUS 5G"}


def test_ambiguous_variant_shared_across_two_real_options_never_guesses():
    """Real catalog risk: "APX NEXT" and "APX NEXT XE" both have a
    "(4G LTE+5G)" option. If both are in scope for the same attr, the
    variant alone can never distinguish them — must not guess either."""
    attr = ConfigAttr(
        entity_id=1, variable_name="hWVersion_astro", display_label="Hardware Version",
        required=False, default_value="", select_type="single",
        options=_menu([
            ("NEXT ENHANCED LTE PLUS 5G", "APX NEXT (4G LTE+5G)"),
            ("APX NEXT XE 4G LTE PLUS 5G", "APX NEXT XE (4G LTE+5G)"),
        ]),
    )
    eng = CpqEngine()
    hints, _negated = eng.extract_catalog_hints(
        "I'll take the 4G LTE+5G version", [attr],
    )
    assert hints == {}


def test_parenthetical_variant_still_respects_negation():
    attr = ConfigAttr(
        entity_id=1, variable_name="hWVersion_astro", display_label="Hardware Version",
        required=False, default_value="", select_type="single",
        options=_menu([
            ("NEXT ENHANCED LTE PLUS 5G", "APX NEXT (4G LTE+5G)"),
            ("NEXT STANDARD LTE ONLY", "APX NEXT (4G LTE Only)"),
        ]),
    )
    eng = CpqEngine()
    hints, _negated = eng.extract_catalog_hints(
        "not the 4G LTE+5G version, the other one", [attr],
    )
    assert "hWVersion_astro" not in hints


def test_generalizes_to_a_second_independent_catalog_svx():
    """Cross-catalog validation (user-provided SVX.xml): confirms the fix
    isn't overfit to APX_next.xml's specific option text, and that a
    parenthetical suffix must ALSO look like a technical code (digit or
    slash), not just be multi-word, before being trusted — raven review
    flagged that multi-word alone is too weak a bar for a short, isolated
    fragment plucked out of context ("Best Value", "desktop or In-vehicle"
    read like ordinary prose, unlike a full catalog-specific option
    string). "1 Year (Standard)"-style and "Conventional (CDEM)"-style
    suffixes both correctly stay unresolved; a real, code-bearing SVX
    variant ("(4G LTE+5G)"-shaped) still resolves via the same mechanism
    proven in APX_next.xml above."""
    eng = CpqEngine()
    charger = ConfigAttr(
        entity_id=1, variable_name="chargerType_viSoln", display_label="Charger Type",
        required=False, default_value="", select_type="single",
        options=_menu([
            ("SPARE_CHG_DESKTOP_INVEHICLE", "Spare Battery Charger (desktop or In-vehicle)"),
            ("SPARE_CHG_MULTI", "Spare Battery Charger (multi-unit)"),
        ]),
    )
    hints, _ = eng.extract_catalog_hints(
        "I need the desktop or in-vehicle charger", [charger],
    )
    assert hints == {}, "multi-word but no digit/slash — not a trusted code, must not guess"

    mode = ConfigAttr(
        entity_id=2, variable_name="operatingModeType_viSoln", display_label="Operating Mode",
        required=False, default_value="", select_type="single",
        options=_menu([("CONVENTIONAL_CDEM", "Conventional (CDEM)"), ("TRUNKING_PDEG", "Trunking (PDEG)")]),
    )
    hints2, _ = eng.extract_catalog_hints("I want the CDEM mode", [mode])
    assert hints2 == {}, "bare single-word variant must stay unresolved (D2 never-guess)"

    # Real APX_next.xml option text — "UHF (403-470 MHz)" / "Whip (450-520 MHZ)".
    band = ConfigAttr(
        entity_id=3, variable_name="freqRange_astro", display_label="Frequency Range",
        required=False, default_value="", select_type="single",
        options=_menu([
            ("FREQ_UHF_403_470", "UHF (403-470 MHz)"),
            ("ANT_WHIP_450_520", "Whip (450-520 MHZ)"),
        ]),
    )
    hints3, _ = eng.extract_catalog_hints("I need the 403-470 MHz range", [band])
    assert hints3 == {"freqRange_astro": "FREQ_UHF_403_470"}, (
        "a real digit-bearing variant code still resolves"
    )


def test_option_without_parens_is_unaffected():
    attr = ConfigAttr(
        entity_id=1, variable_name="hWVersion_astro", display_label="Hardware Version",
        required=False, default_value="", select_type="single",
        options=_menu([("STANDARD", "Standard Hardware Version")]),
    )
    eng = CpqEngine()
    hints, _negated = eng.extract_catalog_hints(
        "give me the standard hardware version", [attr],
    )
    assert hints == {"hWVersion_astro": "STANDARD"}


def test_parenthetical_suffix_helper_rejects_shapes_it_cannot_safely_parse():
    """Raven review: nested/unbalanced parens must never yield a corrupted
    fragment — reject rather than guess at a shape this simple parser
    can't handle."""
    assert _parenthetical_suffix("APX NEXT (4G LTE+5G)") == "4G LTE+5G"
    assert _parenthetical_suffix("APX (FOO (BAR))") is None, "nested parens must be rejected"
    assert _parenthetical_suffix("APX NEXT ()") is None, "empty parens have no suffix"
    assert _parenthetical_suffix("APX (NEXT") is None, "unmatched opening paren"
    assert _parenthetical_suffix("APX NEXT") is None, "no parens at all"
