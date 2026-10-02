"""Flag, user-source, required-anchor and no-op behaviour of the
not-applicable guard (dev-rv-msi #362/#364/#365 port)."""
from __future__ import annotations

import pytest

from aryx.config import get_settings
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption

_OPTS = [
    MenuOption(item_value="A", display_name="A", order=1),
    MenuOption(item_value="B", display_name="B", order=2),
]


@pytest.fixture(autouse=True)
def _reset_flag():
    s = get_settings()
    prev = s.cpq_not_applicable_guard_enabled
    yield
    s.cpq_not_applicable_guard_enabled = prev


def _attr(vn, entity_id=2, required=False):
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=vn,
        required=required, default_value="", select_type="single", options=_OPTS,
    )


def _mock(monkeypatch, *, candidates=("APX900",), governed=False):
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: candidates,
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: governed,
    )


def _run(attr, vn, **kw):
    return CpqEngine().auto_fill(
        [attr], hints={}, governed_ids={attr.entity_id}, rule_governed_ids=set(),
        display_order={vn: 20}, workspace_id=97, catalog_prefix="Astro25Configdata",
        product_anchor_hint="I want APX 900 for US", **kw,
    )


def _blind(vn):
    return {
        "already_filled": {vn: "A"},
        "filled_source": {vn: "auto"},
    }


def test_flag_default_is_off():
    assert get_settings().cpq_not_applicable_guard_enabled is False


def test_flag_off_wrong_fill_is_not_cleared(monkeypatch):
    _mock(monkeypatch)
    get_settings().cpq_not_applicable_guard_enabled = False
    filled, _d, _p = _run(_attr("cloudRegion_astro"), "cloudRegion_astro",
                          **_blind("cloudRegion_astro"))
    assert "cloudRegion_astro" in filled


def test_flag_off_prune_not_called(monkeypatch):
    _mock(monkeypatch)
    get_settings().cpq_not_applicable_guard_enabled = False
    called = []
    monkeypatch.setattr(
        CpqEngine, "_attrs_confirmed_not_applicable_for_hint",
        staticmethod(lambda p, *a, **k: called.append(1) or p),
    )
    _run(_attr("x_astro"), "x_astro")
    assert not called


def test_flag_on_prune_is_called(monkeypatch):
    _mock(monkeypatch)
    get_settings().cpq_not_applicable_guard_enabled = True
    called = []
    monkeypatch.setattr(
        CpqEngine, "_attrs_confirmed_not_applicable_for_hint",
        staticmethod(lambda p, *a, **k: called.append(1) or p),
    )
    _run(_attr("x_astro"), "x_astro")
    assert called


def test_user_sourced_value_survives(monkeypatch):
    _mock(monkeypatch)
    get_settings().cpq_not_applicable_guard_enabled = True
    filled, _d, _p = _run(
        _attr("cloudRegion_astro"), "cloudRegion_astro",
        already_filled={"cloudRegion_astro": "A"},
        filled_source={"cloudRegion_astro": "user"},
    )
    assert filled.get("cloudRegion_astro") == "A"


def test_user_sourced_hardware_version_survives(monkeypatch):
    _mock(monkeypatch)
    get_settings().cpq_not_applicable_guard_enabled = True
    filled, _d, _p = _run(
        _attr("hWVersion_astro", entity_id=1), "hWVersion_astro",
        already_filled={"hWVersion_astro": "A"},
        filled_source={"hWVersion_astro": "user"},
    )
    assert filled.get("hWVersion_astro") == "A"


def test_required_attr_survives_even_with_zero_governance(monkeypatch):
    _mock(monkeypatch)
    get_settings().cpq_not_applicable_guard_enabled = True
    filled, _d, _p = _run(
        _attr("countryRegion_astro", required=True), "countryRegion_astro",
        **_blind("countryRegion_astro"),
    )
    assert filled.get("countryRegion_astro") == "A"


def test_blind_filled_value_cleared_flag_on(monkeypatch):
    _mock(monkeypatch)
    get_settings().cpq_not_applicable_guard_enabled = True
    attr = _attr("cloudRegion_astro")
    filled, _d, pending = _run(attr, "cloudRegion_astro", **_blind("cloudRegion_astro"))
    assert "cloudRegion_astro" not in filled and attr not in pending


@pytest.mark.parametrize("candidates", [(), ("APX900", "APXNEXT")])
def test_unresolved_or_ambiguous_hint_is_noop(monkeypatch, candidates):
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: candidates,
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: cm == "APXNEXT",
    )
    get_settings().cpq_not_applicable_guard_enabled = True
    filled, _d, _p = _run(_attr("cloudRegion_astro"), "cloudRegion_astro",
                          **_blind("cloudRegion_astro"))
    assert filled.get("cloudRegion_astro") == "A"


def test_apx_next_style_hw_version_unaffected(monkeypatch):
    _mock(monkeypatch, candidates=("APXNEXTENHANCED",), governed=True)
    get_settings().cpq_not_applicable_guard_enabled = True
    attr = _attr("hWVersion_astro", entity_id=1)
    filled, _d, pending = _run(attr, "hWVersion_astro")
    assert attr in pending and "hWVersion_astro" not in filled
