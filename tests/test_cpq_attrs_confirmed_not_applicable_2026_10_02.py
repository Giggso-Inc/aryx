"""RCA 2026-09-24 (Professional Services asked on APX 900): a shared,
multi-model layout export (astro25_config_layout.txt, used by all 15
"AstroDevicesPortable" models including both APX 900 and APX 3000) marks
components `hide: false` for the whole file, not per model, and the
catalog's dynamic hide-rules only exclude a short named list of exceptions
instead of scoping inclusion to the right product line -- so any attribute
not on an exclusion list (e.g. deviceManagementTraining_astro/
numberOfSeats_astro, "Professional Services") leaks through and gets asked
on every model sharing the layout.

CpqEngine._attrs_confirmed_not_applicable_for_hint generalizes the existing,
reviewed `_hardware_version_confirmed_not_applicable` one-sided "real Data
Table evidence, never a guess" contract (see
tests/test_cpq_hardware_version_apx3000_scoping_2026_09_21.py) from
Hardware Version alone to every pending attribute: drop an attr only when
the resolved device's real CPQModel candidate(s) are NEVER, for any of
them, seen governing it anywhere in the Data Table -- same "any() governed
-> keep, none governed -> drop" rule, same fall-through-to-unchanged
behavior for every ambiguous/unresolved case.
"""
from __future__ import annotations

import pytest

from aryx.config import get_settings


@pytest.fixture(autouse=True)
def _guard_on():
    s = get_settings()
    prev = s.cpq_not_applicable_guard_enabled
    s.cpq_not_applicable_guard_enabled = True
    yield
    s.cpq_not_applicable_guard_enabled = prev


from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr


def _attr(vn: str, required: bool = False) -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name=vn, display_label=vn,
        required=required, default_value="", select_type="single", options=[],
    )


def test_returns_pending_unchanged_with_no_hint_text():
    pending = [_attr("deviceManagementTraining_astro")]
    result = CpqEngine._attrs_confirmed_not_applicable_for_hint(
        pending, None, workspace_id=97, catalog_prefix="Astro25Configdata",
    )
    assert result == pending


def test_returns_pending_unchanged_with_no_workspace_id():
    pending = [_attr("deviceManagementTraining_astro")]
    result = CpqEngine._attrs_confirmed_not_applicable_for_hint(
        pending, "I want APX 900 for US", workspace_id=None,
    )
    assert result == pending


def test_returns_pending_unchanged_when_hint_resolves_to_no_candidates(monkeypatch):
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: (),  # unresolved / ambiguous -- never guess
    )
    pending = [_attr("deviceManagementTraining_astro")]
    result = CpqEngine._attrs_confirmed_not_applicable_for_hint(
        pending, "some ambiguous phrase", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert result == pending


def test_drops_attr_confirmed_never_governed_for_resolved_device(monkeypatch):
    """APX 900 case: Professional Services attrs are never governed for
    APX900's real CPQModel -- must be dropped from pending."""
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: ("APX900",),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: False,
    )
    pending = [
        _attr("deviceManagementTraining_astro"),
        _attr("numberOfSeats_astro"),
    ]
    result = CpqEngine._attrs_confirmed_not_applicable_for_hint(
        pending, "I want APX 900 for US", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert result == []


def test_keeps_attr_genuinely_governed_for_the_resolved_device(monkeypatch):
    """APX NEXT case: same attribute IS governed for APX NEXT's CPQModel --
    must stay pending, exactly like today (no change in behavior)."""
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: ("APXNEXTENHANCED",),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: True,
    )
    pending = [_attr("deviceManagementTraining_astro")]
    result = CpqEngine._attrs_confirmed_not_applicable_for_hint(
        pending, "I want APX NEXT for USA", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert result == pending


def test_keeps_attr_when_any_of_multiple_candidates_governs_it(monkeypatch):
    """Multiple real CPQModel candidates resolved -- if EVEN ONE governs the
    attribute, never drop it (mirrors _hardware_version_confirmed_not_
    applicable's identical multi-candidate 'any' convention)."""
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: ("APX900", "APXNEXTENHANCED"),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: cm == "APXNEXTENHANCED",
    )
    pending = [_attr("deviceManagementTraining_astro")]
    result = CpqEngine._attrs_confirmed_not_applicable_for_hint(
        pending, "some text matching two real products", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert result == pending


def test_keeps_attrs_with_mixed_governance_only_drops_the_ungoverned_ones(monkeypatch):
    """A realistic mixed pending list: one attr genuinely applies to APX
    900, one doesn't -- only the second is dropped."""
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: ("APX900",),
    )
    governed = {"wirelessCarrier_astro"}
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: vn in governed,
    )
    pending = [_attr("wirelessCarrier_astro"), _attr("deviceManagementTraining_astro")]
    result = CpqEngine._attrs_confirmed_not_applicable_for_hint(
        pending, "I want APX 900 for US", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert [a.variable_name for a in result] == ["wirelessCarrier_astro"]


def test_empty_pending_short_circuits():
    result = CpqEngine._attrs_confirmed_not_applicable_for_hint(
        [], "I want APX 900 for US", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert result == []


def test_hardware_version_attr_survives_even_with_zero_governance(monkeypatch):
    """Raven review finding (PR #362): the docstring promises structural
    anchors are exempted, but nothing enforced it. Hardware Version is
    typically decision-key/free-input driven, not Data-Table-rule-governed
    -- a resolved candidate genuinely showing zero sequence-row coverage
    for it is plausible and must NOT be read as "confirmed inapplicable"
    the way it safely can be for an ordinary catch-all attribute. Dropping
    a mandatory anchor here would violate this codebase's own
    never-silently-drop invariant."""
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: ("APX900",),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: False,  # zero governance for everything
    )
    pending = [_attr("hWVersion_astro")]
    result = CpqEngine._attrs_confirmed_not_applicable_for_hint(
        pending, "I want APX 900 for US", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert result == pending


def test_product_line_selector_survives_even_with_zero_governance(monkeypatch):
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: ("APX900",),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: False,
    )
    pending = [_attr("productSelectionProduct_all")]
    result = CpqEngine._attrs_confirmed_not_applicable_for_hint(
        pending, "I want APX 900 for US", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert result == pending


def test_country_region_decision_attr_survives_even_with_zero_governance(monkeypatch):
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: ("APX900",),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: False,
    )
    pending = [_attr("ultimateDestinationCountry", required=True)]
    result = CpqEngine._attrs_confirmed_not_applicable_for_hint(
        pending, "I want APX 900 for US", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert result == pending


def test_anchors_kept_ordinary_attr_still_dropped_in_the_same_pass(monkeypatch):
    """Mixed pending list: structural anchors survive unconditionally,
    while an ordinary catch-all attr with genuinely zero governance is
    still dropped in the same call -- the anchor exemption doesn't
    accidentally disable the filter entirely."""
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: ("APX900",),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: False,
    )
    pending = [
        _attr("hWVersion_astro"),
        _attr("ultimateDestinationCountry", required=True),
        _attr("productSelectionProduct_all"),
        _attr("deviceManagementTraining_astro"),
    ]
    result = CpqEngine._attrs_confirmed_not_applicable_for_hint(
        pending, "I want APX 900 for US", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert [a.variable_name for a in result] == [
        "hWVersion_astro", "ultimateDestinationCountry", "productSelectionProduct_all",
    ]
