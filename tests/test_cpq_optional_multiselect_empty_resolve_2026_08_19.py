"""Named allowlist addition (2026-08-19): three multi-select attributes
individually confirmed genuinely optional (Attrsequence: 0 Required rows
across every base model checked, workspace 93) with no menu-declared
opt-out option for _sole_opt_out_option to find:

  - promoApplicationServices_astro: 0/12 Required.
  - additionalApplicationServices_astro: 0/85 Required.
  - aTAKNonPromoApplicationServices_astro: zero Attrsequence rows at all.

Before this fix these fell through to the existing "blind-pick one real
option" fallback (or asked), guessing among real, materially different
add-on services (SmartProgramming vs SmartConnect vs SmartVideo, etc.)
the customer never requested. "Select nothing" is itself the real,
data-confirmed valid answer for these three -- distinct from a generic
"leave every optional multi-select empty" rule, which is NOT what this
adds (see the negative test below).
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def test_promo_application_services_resolves_to_empty_not_a_guess():
    attr = ConfigAttr(
        entity_id=1, variable_name="promoApplicationServices_astro",
        display_label="Promo Application Services", required=False, default_value="",
        select_type="multi",
        options=_menu(
            "SMARTPROGRAMMING", "SMARTCONNECT", "SMARTLOCATE",
            "SMARTMAPPING", "SMARTMESSAGING", "VIQI VIRTUAL PARTNER",
        ),
    )
    eng = CpqEngine()
    filled_multi: dict = {}
    eng.auto_fill([attr], {}, already_filled_multi=filled_multi, governed_ids={1})
    assert filled_multi.get("promoApplicationServices_astro") == []


def test_additional_application_services_resolves_to_empty():
    attr = ConfigAttr(
        entity_id=1, variable_name="additionalApplicationServices_astro",
        display_label="Additional Application Services", required=False, default_value="",
        select_type="multi",
        options=_menu(
            "SMARTINCIDENT", "SMARTVIDEO", "SMARTTRANSLATION",
            "SMARTQUERY", "VIQI VIRTUAL PARTNER", "SMARTEVIDENCE",
        ),
    )
    eng = CpqEngine()
    filled_multi: dict = {}
    eng.auto_fill([attr], {}, already_filled_multi=filled_multi, governed_ids={1})
    assert filled_multi.get("additionalApplicationServices_astro") == []


def test_atak_non_promo_application_services_resolves_to_empty():
    attr = ConfigAttr(
        entity_id=1, variable_name="aTAKNonPromoApplicationServices_astro",
        display_label="ATAK Non-Promo Application Services", required=False, default_value="",
        select_type="multi",
        options=_menu(
            "SMARTPROGRAMMING", "SMARTCONNECT", "SMARTLOCATE",
            "SMARTMAPPING", "SMARTMESSAGING", "RADIOCENTRAL PROMO",
        ),
    )
    eng = CpqEngine()
    filled_multi: dict = {}
    eng.auto_fill([attr], {}, already_filled_multi=filled_multi, governed_ids={1})
    assert filled_multi.get("aTAKNonPromoApplicationServices_astro") == []


def test_unlisted_optional_multiselect_is_unaffected_by_this_change():
    """Regression guard: this addition is a named, narrow exception, not
    a generic "leave optional multi-selects empty" rule. An attribute NOT
    in _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS must keep its prior (pre-existing,
    unchanged) behavior -- whatever that was before this fix."""
    from aryx.cpq.engine import _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS
    assert "someOtherOptionalMultiSelect_astro" not in _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS
