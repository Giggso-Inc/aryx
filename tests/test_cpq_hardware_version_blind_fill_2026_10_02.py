"""RCA 2026-09-24/25 (live-confirmed on a fresh APX 900 AND APX 3000 session,
two different base models T7614A and T8343A): `hWVersion_astro` kept getting
blind-filled with an APX-NEXT-only value ("NEXT ENHANCED LTE PLUS 5G" / "APX
NEXT (4G LTE+5G)") even though `_hardware_version_confirmed_not_applicable`
(docs/Hardware_Version_APX3000_Product_Anchoring_Issue.md v2.2) already
correctly stops it from being FORCED as an always-ask anchor for these
devices. Root cause: that check only feeds `is_decision_attr` -- it never
stopped `is_governed` from being True (other hiding rules reference
hWVersion_astro as a condition even where it's never itself governed),
which let the attr fall through into auto_fill's ordinary blind first-by-
order ("default_first_available") fallback. The wrong value then cascaded
into cloudRegion_astro/encryptionVPS_astro/regionalSrvMgr*_astro -- none of
which exist on the real APX 900/APX 3000 native UI at all.

This suite covers the new early guard in auto_fill's per-attr loop: when
_hardware_version_confirmed_not_applicable is True, hWVersion_astro is
skipped entirely (never filled, never asked, never blind-picked) -- and an
already-wrongly-filled value from an earlier pass/turn is cleared, not just
prevented going forward. Same one-sided, never-guess contract as the
precedent it extends: only ever removes/skips, only when the device is
confidently resolved AND real data confirms it; every ambiguous/unresolved
hint is a no-op, identical to today's behavior.
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


from unittest.mock import patch

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption

_HW_OPTIONS = [
    MenuOption(item_value="NEXT ENHANCED LTE PLUS 5G", display_name="APX NEXT (4G LTE+5G)", order=1),
    MenuOption(item_value="NEXT LTE ONLY", display_name="APX NEXT (4G LTE Only)", order=2),
]


def _hw_attr(entity_id: int = 1) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name="hWVersion_astro", display_label="Hardware Version",
        required=False, default_value="", select_type="single", options=_HW_OPTIONS,
    )


def _confirmed_not_applicable(monkeypatch, *, candidates=("APX900",)):
    """APX 900/APX 3000-shaped mocks: a confident device resolves, and it
    never governs Hardware Version anywhere in the Data Table."""
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: candidates,
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: False,
    )


def test_hw_version_never_blind_filled_when_confirmed_not_applicable(monkeypatch):
    _confirmed_not_applicable(monkeypatch)
    attr = _hw_attr()
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill(
        [attr], hints={}, governed_ids={1}, rule_governed_ids=set(),
        display_order={"hWVersion_astro": 5},
        workspace_id=97, catalog_prefix="Astro25Configdata",
        product_anchor_hint="I want APX 900 for US",
    )
    assert "hWVersion_astro" not in filled
    assert attr not in pending


def test_hw_version_already_wrongly_filled_gets_cleared(monkeypatch):
    """Self-healing case: a PRIOR pass or turn already blind-filled the
    wrong value into `already_filled` -- the new guard must clear it, not
    just prevent a fresh fill."""
    _confirmed_not_applicable(monkeypatch)
    attr = _hw_attr()
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill(
        [attr], hints={},
        already_filled={"hWVersion_astro": "NEXT ENHANCED LTE PLUS 5G"},
        filled_source={"hWVersion_astro": "default_first_available"},
        governed_ids={1}, rule_governed_ids=set(),
        display_order={"hWVersion_astro": 5},
        workspace_id=97, catalog_prefix="Astro25Configdata",
        product_anchor_hint="I want APX 900 for US",
    )
    assert "hWVersion_astro" not in filled
    assert attr not in pending


def test_hw_version_still_blind_fillable_when_genuinely_governed(monkeypatch):
    """APX NEXT case: Hardware Version genuinely IS governed for the
    resolved device -- must keep today's exact behavior (still eligible
    for the ordinary blind first-by-order fallback), completely unaffected
    by this fix."""
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: ("APXNEXTENHANCED",),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: True,
    )
    attr = _hw_attr()
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill(
        [attr], hints={}, governed_ids={1}, rule_governed_ids=set(),
        display_order={"hWVersion_astro": 5},
        workspace_id=97, catalog_prefix="Astro25Configdata",
        product_anchor_hint="I want APX NEXT for USA",
    )
    # is_decision_attr stays True here (Hardware Version genuinely governed)
    # so it's forced onto pending, exactly like today -- never silently
    # blind-filled OR silently dropped for a device that really has this
    # concept.
    assert attr in pending
    assert "hWVersion_astro" not in filled


def test_hw_version_unaffected_when_hint_is_ambiguous(monkeypatch):
    """No confident device resolution (e.g. resolve_product_cpq_models_
    from_hint returns nothing) -- must fall through to today's unchanged
    behavior, never guess in either direction."""
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: (),
    )
    attr = _hw_attr()
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill(
        [attr], hints={}, governed_ids={1}, rule_governed_ids=set(),
        display_order={"hWVersion_astro": 5},
        workspace_id=97, catalog_prefix="Astro25Configdata",
        product_anchor_hint="some ambiguous phrase",
    )
    # Hardware Version stays mandatory -- unresolved/ambiguous keeps
    # today's exact "always ask" behavior.
    assert attr in pending
    assert "hWVersion_astro" not in filled


def test_hw_version_unaffected_with_no_hint_at_all():
    """No product_anchor_hint supplied (default None) -- every existing
    caller that doesn't pass it keeps today's exact behavior."""
    attr = _hw_attr()
    eng = CpqEngine()
    filled, _display, pending = eng.auto_fill(
        [attr], hints={}, governed_ids={1}, rule_governed_ids=set(),
        display_order={"hWVersion_astro": 5},
        workspace_id=97, catalog_prefix="Astro25Configdata",
    )
    assert attr in pending
    assert "hWVersion_astro" not in filled
