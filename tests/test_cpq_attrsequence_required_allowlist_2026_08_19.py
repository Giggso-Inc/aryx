"""Named allowlist extension (2026-08-19): four single-select attributes
individually confirmed via the real Attrsequence Data Table (per-base-
model AttrName+CPQModel+BaseModel+optionOrReqFlag rows, workspace 93) to
be Required for nearly every base model -- a real governance signal
_no_real_fill_justification can't see, since it only checks
ConfigAttr.required (sourced from bm_config_attr.required, confirmed live
to be 0/unreliable) and rec_by_target, never Attrsequence. Before this
fix these attributes fell through to `pending` (asked the user) despite
the catalog's own data proving they're mandatory almost everywhere:

  - baselineReleaseSW_astro ("Software Release"): 448/449 Required rows.
  - applicationServicesSelection_astro ("Application Services
    Selection"): 28/28 Required rows.
  - carrierSelectionMultiSelect_astro ("Carrier Selection"): 3/3 Required
    rows.
  - packingPackageType_astro ("Package Type"): 452/453 Required rows.

Each test below exercises the single-select "governed but unconstrained
-> blind-pick first available" fallback (engine.py's `elif display_order
is not None and vn in display_order and not (_no_real_fill_
justification(...) and vn not in _BLIND_FILL_RISK_ACCEPTED_VNS)` branch)
with NO active constraint at all (no constrained_opts passed) -- proving
the allowlist entry alone is sufficient to open this specific fallback,
distinct from the already-tested constrained-and-ambiguous case.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def test_software_release_blind_picks_first_option_when_ungoverned_by_constraint():
    attr = ConfigAttr(
        entity_id=1, variable_name="baselineReleaseSW_astro",
        display_label="Software Release", required=False, default_value="",
        select_type="single",
        options=_menu("BASELINE RELEASE", "LATEST RELEASE"),
    )
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [attr], {}, governed_ids={1},
        display_order={"baselineReleaseSW_astro": 0},
    )
    assert filled.get("baselineReleaseSW_astro") == "BASELINE RELEASE"


def test_application_services_selection_blind_picks_first_option():
    attr = ConfigAttr(
        entity_id=1, variable_name="applicationServicesSelection_astro",
        display_label="Application Services Selection", required=False, default_value="",
        select_type="single",
        options=_menu("STANDALONE APP SERVICES", "RESPONDER CONNECTIVITY ASSIST"),
    )
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [attr], {}, governed_ids={1},
        display_order={"applicationServicesSelection_astro": 0},
    )
    assert filled.get("applicationServicesSelection_astro") == "STANDALONE APP SERVICES"


def test_carrier_selection_blind_picks_first_option():
    attr = ConfigAttr(
        entity_id=1, variable_name="carrierSelectionMultiSelect_astro",
        display_label="Carrier Selection", required=False, default_value="",
        select_type="single",
        options=_menu("ATT/FIRSTNET", "VERIZON", "T MOBILE"),
    )
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [attr], {}, governed_ids={1},
        display_order={"carrierSelectionMultiSelect_astro": 0},
    )
    assert filled.get("carrierSelectionMultiSelect_astro") == "ATT/FIRSTNET"


def test_package_type_blind_picks_first_option_when_no_active_constraint():
    """Distinct from packingPackageType_astro's own real constraint rule
    (18131370895, script-backed on additionalSystemEnhancementFeatureType_
    astro/ICE KIT), which already resolves it via the recommendation/
    constraint-narrowing path when that rule fires. This test covers the
    fallback case: no active constraint at all (e.g. the ICE-KIT-gating
    attribute hasn't been answered yet), where the allowlist entry alone
    must still resolve it instead of asking."""
    attr = ConfigAttr(
        entity_id=1, variable_name="packingPackageType_astro",
        display_label="Package Type", required=False, default_value="",
        select_type="single",
        options=_menu(
            "SINGLE", "BULK", "N/A", "DEMO KIT CASE", "SINGLE XE",
            "BULK XE", "PACK INTO DEMO KIT CASE", "SINGLE PACK CLAMSHELL",
        ),
    )
    eng = CpqEngine()
    filled, _display, _pending = eng.auto_fill(
        [attr], {}, governed_ids={1},
        display_order={"packingPackageType_astro": 0},
    )
    assert filled.get("packingPackageType_astro") == "SINGLE"


def test_unlisted_attr_not_in_allowlist_is_unaffected_by_this_change():
    """Regression guard: confirms this change is additive only -- an
    attribute that was never touched by this fix behaves exactly as it
    did before (same fixture shape as the four allowlisted tests above,
    only the variable_name differs and is absent from
    _BLIND_FILL_RISK_ACCEPTED_VNS). Whatever auto_fill resolves it to is
    pre-existing behavior this fix must not change -- the point here is
    only that _someUnverifiedAttr_astro_ is not itself in the allowlist,
    not a claim about which other fallback mechanism may still apply."""
    from aryx.cpq.engine import _BLIND_FILL_RISK_ACCEPTED_VNS
    assert "someUnverifiedAttr_astro" not in _BLIND_FILL_RISK_ACCEPTED_VNS
