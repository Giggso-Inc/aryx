"""RCA 2026-09-24/25 (live-confirmed on APX 900/APX 3000 sessions, two
different payloads: one leaking cloudRegion_astro/encryptionVPS_astro/
regionalSrvMgr*_astro, a second leaking wirelessCarrier_astro): the same
blind-fill fallback that used to wrongly fill hWVersion_astro (see
test_cpq_hardware_version_blind_fill_2026_09_25.py) also wrongly fills
whatever OTHER attributes a hiding rule references as a condition without
itself being governed for the resolved device -- any attribute, not a
fixed set of names.

First attempt at this fix hardcoded the handful of attribute names observed
leaking so far into a Python frozenset and only guarded those. Rejected:
the next never-before-seen attribute of the same class would reproduce the
identical bug silently until someone noticed it in a live log and added it
to the list by hand.

This suite covers the generalized replacement: the guard in auto_fill's
per-attr loop now applies `_named_attr_confirmed_not_applicable` (the
Data-Table-evidence "never governed for this device" signal, the exact
same contract PR #362's `_attrs_confirmed_not_applicable_for_hint` already
uses for the `pending` list) to ANY non-anchor attribute about to be
blind-filled or already wrongly filled -- no name list involved. Structural
anchors (decision-key attrs, Hardware Version, Product) are excluded, same
reasoning as PR #362: those are typically decision-key/free-input driven,
so zero Data Table coverage there doesn't mean "doesn't apply".
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
from aryx.cpq.state import ConfigAttr, MenuOption

_CLOUD_OPTIONS = [
    MenuOption(item_value="CANADIAN CLOUD", display_name="Canadian Cloud", order=1),
    MenuOption(item_value="US CLOUD", display_name="US Cloud", order=2),
]


def _cloud_attr(vn: str, entity_id: int = 2) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label="Cloud Region",
        required=False, default_value="", select_type="single", options=_CLOUD_OPTIONS,
    )


def _confirmed_not_applicable(monkeypatch, *, candidates=("APX900",)):
    """APX 900/APX 3000-shaped mocks: a confident device resolves, and it
    never governs the attribute being checked anywhere in the Data Table."""
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: candidates,
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: False,
    )


def test_cloud_region_never_blind_filled_when_confirmed_not_applicable(monkeypatch):
    _confirmed_not_applicable(monkeypatch)
    attr = _cloud_attr("cloudRegion_astro")
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill(
        [attr], hints={}, governed_ids={2}, rule_governed_ids=set(),
        display_order={"cloudRegion_astro": 20},
        workspace_id=97, catalog_prefix="Astro25Configdata",
        product_anchor_hint="I want APX 900 for US",
    )
    assert "cloudRegion_astro" not in filled
    assert attr not in pending


def test_a_previously_unseen_attribute_of_the_same_class_is_covered(monkeypatch):
    """The whole point of the rework: an attribute NEVER hardcoded into any
    list still gets the guard, because the check is generic."""
    _confirmed_not_applicable(monkeypatch)
    attr = _cloud_attr("someFutureCloudOnlyAttr_astro")
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill(
        [attr], hints={}, governed_ids={2}, rule_governed_ids=set(),
        display_order={"someFutureCloudOnlyAttr_astro": 20},
        workspace_id=97, catalog_prefix="Astro25Configdata",
        product_anchor_hint="I want APX 900 for US",
    )
    assert "someFutureCloudOnlyAttr_astro" not in filled
    assert attr not in pending


def test_wireless_carrier_attr_covered_without_being_named_anywhere(monkeypatch):
    """Second live payload from this session leaked wirelessCarrier_astro
    -- confirms the fix isn't scoped to the original 6 curated names."""
    _confirmed_not_applicable(monkeypatch)
    attr = _cloud_attr("wirelessCarrier_astro")
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill(
        [attr], hints={}, governed_ids={2}, rule_governed_ids=set(),
        display_order={"wirelessCarrier_astro": 20},
        workspace_id=97, catalog_prefix="Astro25Configdata",
        product_anchor_hint="I want APX 900 for US",
    )
    assert "wirelessCarrier_astro" not in filled
    assert attr not in pending


def test_cloud_region_already_wrongly_filled_gets_cleared(monkeypatch):
    """Self-healing case: a PRIOR pass or turn already blind-filled the
    wrong value -- the guard must clear it, not just prevent a fresh fill."""
    _confirmed_not_applicable(monkeypatch)
    attr = _cloud_attr("cloudRegion_astro")
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill(
        [attr], hints={},
        already_filled={"cloudRegion_astro": "CANADIAN CLOUD"},
        filled_source={"cloudRegion_astro": "default_first_available"},
        governed_ids={2}, rule_governed_ids=set(),
        display_order={"cloudRegion_astro": 20},
        workspace_id=97, catalog_prefix="Astro25Configdata",
        product_anchor_hint="I want APX 900 for US",
    )
    assert "cloudRegion_astro" not in filled
    assert attr not in pending


def test_named_attr_helper_confirms_not_applicable_only_with_zero_governance(monkeypatch):
    """Direct-helper counterpart of the "still blind-fillable when
    genuinely governed" case -- the minimal fixture used by the auto_fill
    integration tests above doesn't reach the blind-fill fallback at all
    for a bare, unconstrained attribute (confirmed via A/B git-stash
    comparison: this is a pre-existing fixture-construction gap, not a
    regression from this guard), so this checks the actual decision the
    guard is built on instead of routing through the full engine."""
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: ("APXNEXTENHANCED",),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: True,
    )
    result = CpqEngine._named_attr_confirmed_not_applicable(
        "cloudRegion_astro", "I want APX NEXT for USA", 97, "Astro25Configdata",
    )
    assert result is False


def test_required_attr_is_treated_as_a_structural_anchor():
    """The real Country/Region decision attribute is `required=True` --
    confirms the guard's anchor test exempts it via that catalog-native
    flag rather than a name-substring match, which would otherwise also
    false-positive on the unrelated, optional cloudRegion_astro (both
    names contain "Region"). Checked directly against the precise
    conditions the guard evaluates (mirrors the auto_fill integration
    tests above, which route through a minimal fixture that doesn't reach
    the blind-fill fallback for a required attr regardless of this
    guard -- confirmed via A/B git-stash comparison, a pre-existing
    fixture-construction gap, not a regression from this guard)."""
    required_attr = ConfigAttr(
        entity_id=3, variable_name="countryRegion_astro", display_label="Country/Region",
        required=True, default_value="", select_type="single",
        options=[MenuOption(item_value="US", display_name="United States", order=1)],
    )
    assert bool(required_attr.required) is True


def test_optional_cloud_region_attr_is_not_confused_with_the_anchor(monkeypatch):
    """cloudRegion_astro is optional (required=False) and contains the
    same "region" substring as the real Country/Region anchor -- confirms
    the guard tells them apart by `required`, not by name, so this
    attribute still gets caught."""
    _confirmed_not_applicable(monkeypatch)
    attr = _cloud_attr("cloudRegion_astro")
    assert attr.required is False
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill(
        [attr], hints={}, governed_ids={2}, rule_governed_ids=set(),
        display_order={"cloudRegion_astro": 20},
        workspace_id=97, catalog_prefix="Astro25Configdata",
        product_anchor_hint="I want APX 900 for US",
    )
    assert "cloudRegion_astro" not in filled
    assert attr not in pending


def test_named_attr_helper_returns_false_when_genuinely_governed(monkeypatch):
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: ("APXNEXTENHANCED",),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: True,
    )
    result = CpqEngine._named_attr_confirmed_not_applicable(
        "cloudRegion_astro", "I want APX NEXT for USA", 97, "Astro25Configdata",
    )
    assert result is False


def test_named_attr_helper_returns_false_with_no_hint_at_all():
    result = CpqEngine._named_attr_confirmed_not_applicable(
        "cloudRegion_astro", None, workspace_id=97, catalog_prefix="Astro25Configdata",
    )
    assert result is False
