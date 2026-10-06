"""The layout's own `hide: true` stops the always-ask overrides from forcing a question.

SVX regression (workspace 1214, 2026-10-06): after "quote SVX for US" and the model choice, Ask forced
`productSelectionProduct_all` (291 options across every family) although the real SVX screen never
shows it. The always-ask override (`FORCED_ASK_ANCHOR`) sits ahead of the layout-visibility check, and
its only exemption (`skip_always_ask`) was empty because the attribute is *in* the flow, in the layout's
"Hidden" tab. That layout marks it `hide: true`; every APX/Astro layout has `hide: false`.
"""
from __future__ import annotations

import json

import pytest

from aryx.config import get_settings
from aryx.cpq import engine as engine_module
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption

WS, PREFIX = 7, "Video SolutionSvx"


def _component(vn: str, hide: bool) -> dict:
    return {"componentTypeCode": {"lookupCode": "FORM_CONTROL"}, "resourceAttrType": "Text",
            "resourceAttributeVarName": vn, "hide": hide}


def _layout(*components: dict) -> str:
    return json.dumps({"status": "Active", "variableName": "flow", "components": {"items": list(components)}})


class _Source:
    def __init__(self, text: str | None) -> None:
        self.text = text

    def get(self, catalog_name, workspace_id, variant="default"):
        return self.text


@pytest.fixture(autouse=True)
def _fresh_caches():
    for name in ("_LAYOUT_COMPONENTS_CACHE", "_LAYOUT_DISPLAY_ORDER_CACHE", "_LAYOUT_FULL_ORDER_CACHE"):
        getattr(engine_module, name).clear()
    yield
    for name in ("_LAYOUT_COMPONENTS_CACHE", "_LAYOUT_DISPLAY_ORDER_CACHE", "_LAYOUT_FULL_ORDER_CACHE"):
        getattr(engine_module, name).clear()


def _attr(entity_id: int, vn: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=vn, required=False, default_value="",
        options=[MenuOption("A", "A", 1), MenuOption("B", "B", 2), MenuOption("C", "C", 3)],
    )


def _engine_with_layout(monkeypatch, text: str | None) -> CpqEngine:
    monkeypatch.setattr(engine_module, "_DEFAULT_LAYOUT_FILE_SOURCE", _Source(text))
    return CpqEngine()


# --- load_layout_hidden_vns -------------------------------------------------------------------------
def test_hidden_vns_are_exactly_the_components_marked_hide_true(monkeypatch):
    eng = _engine_with_layout(monkeypatch, _layout(
        _component("productSelectionProduct_all", True), _component("ultimateDestinationCountry", False),
        _component("mountType_viSoln", True)))
    assert eng.load_layout_hidden_vns(WS, PREFIX) == {"productSelectionProduct_all", "mountType_viSoln"}


def test_no_layout_is_none_not_an_empty_set(monkeypatch):
    assert _engine_with_layout(monkeypatch, None).load_layout_hidden_vns(WS, PREFIX) is None


def test_an_attribute_missing_from_the_layout_is_not_treated_as_hidden(monkeypatch):
    eng = _engine_with_layout(monkeypatch, _layout(_component("ultimateDestinationCountry", False)))
    assert eng.load_layout_hidden_vns(WS, PREFIX) == set()


# --- resolve_layout_hidden_anchor_skips -------------------------------------------------------------
def test_svx_shape_hidden_product_is_skipped_but_visible_anchors_are_not(monkeypatch):
    eng = _engine_with_layout(monkeypatch, _layout(
        _component("productSelectionProduct_all", True), _component("modelSelectionSelectModel_viSoln", False),
        _component("ultimateDestinationCountry", False)))
    attrs = [_attr(1, "productSelectionProduct_all"), _attr(2, "modelSelectionSelectModel_viSoln"),
             _attr(3, "ultimateDestinationCountry")]
    assert eng.resolve_layout_hidden_anchor_skips(WS, PREFIX, attrs) == {"productSelectionProduct_all"}


def test_apx_shape_product_shown_in_the_layout_is_still_forced(monkeypatch):
    eng = _engine_with_layout(monkeypatch, _layout(
        _component("productSelectionProduct_all", False), _component("ultimateDestinationCountry", False)))
    assert eng.resolve_layout_hidden_anchor_skips(WS, PREFIX, [_attr(1, "productSelectionProduct_all")]) == set()


def test_no_layout_changes_nothing(monkeypatch):
    eng = _engine_with_layout(monkeypatch, None)
    assert eng.resolve_layout_hidden_anchor_skips(WS, PREFIX, [_attr(1, "productSelectionProduct_all")]) == set()


def test_only_attributes_of_this_catalog_are_returned(monkeypatch):
    eng = _engine_with_layout(monkeypatch, _layout(_component("productSelectionProduct_all", True),
                                                   _component("someOtherHidden", True)))
    assert eng.resolve_layout_hidden_anchor_skips(WS, PREFIX, [_attr(1, "productSelectionProduct_all")]) \
        == {"productSelectionProduct_all"}


def test_the_opt_out_flag_restores_todays_behaviour(monkeypatch):
    eng = _engine_with_layout(monkeypatch, _layout(_component("productSelectionProduct_all", True)))
    monkeypatch.setattr(get_settings(), "cpq_layout_hidden_anchor_skip_enabled", False)
    assert eng.resolve_layout_hidden_anchor_skips(WS, PREFIX, [_attr(1, "productSelectionProduct_all")]) == set()


# --- end to end through auto_fill: neither asked nor blind-filled -----------------------------------
def _auto_fill(skip_always_ask):
    return CpqEngine().auto_fill(
        attrs=[_attr(1, "productSelectionProduct_all")], hints={}, governed_ids={1},
        skip_always_ask=skip_always_ask)


def test_product_is_force_asked_without_the_skip():
    filled, _display, pending = _auto_fill(skip_always_ask=None)
    assert "productSelectionProduct_all" not in filled
    assert [a.variable_name for a in pending] == ["productSelectionProduct_all"]


def test_a_layout_hidden_product_is_neither_asked_nor_filled_with_a_foreign_code():
    filled, _display, pending = _auto_fill(skip_always_ask={"productSelectionProduct_all"})
    assert "productSelectionProduct_all" not in filled      # no blind first-by-order ("APX6500") fill
    assert pending == []                                    # and no question


# --- review follow-ups: one helper for every ask path (F01), visible-twice attribute (F02) ---------------
def test_a_vn_placed_twice_once_visible_is_not_hidden(monkeypatch):
    eng = _engine_with_layout(monkeypatch, _layout(
        _component("productSelectionProduct_all", True), _component("productSelectionProduct_all", False),
        _component("mountType_viSoln", True)))
    assert eng.load_layout_hidden_vns(WS, PREFIX) == {"mountType_viSoln"}


def test_the_ask_helper_unions_the_flow_exemption_and_the_layout_hidden_set(monkeypatch):
    eng = _engine_with_layout(monkeypatch, _layout(_component("mountType_viSoln", True)))
    monkeypatch.setattr(eng, "resolve_always_ask_skips", lambda ws, prefix, attrs: {"fromFlow"})
    attrs = [_attr(1, "mountType_viSoln")]
    assert eng.resolve_ask_always_ask_skips(WS, PREFIX, attrs) == {"fromFlow", "mountType_viSoln"}


def test_the_payload_flow_exclusion_keeps_its_flow_only_meaning(monkeypatch):
    """`payload_flow_exclusions` treats a non-empty flow skip set as 'the flow hides the product selector';
    layout-hidden attributes must not leak into it and be stripped from the payload."""
    eng = _engine_with_layout(monkeypatch, _layout(_component("mountType_viSoln", True)))
    monkeypatch.setattr(eng, "resolve_always_ask_skips", lambda ws, prefix, attrs: set())
    monkeypatch.setattr(eng, "model_context_mirror_vns", lambda attrs: {"mirror"})
    assert eng.payload_flow_exclusions(WS, PREFIX, [_attr(1, "mountType_viSoln")]) == {"mirror"}


def test_no_ask_path_builds_skip_always_ask_from_the_flow_exemption_alone():
    """Every caller under aryx/api must use the helper; otherwise a cascade, quantity, clear, activation,
    removal or country-change turn re-asks a layout-hidden Product."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "aryx" / "api"
    offenders = [str(p.relative_to(root)) for p in root.rglob("*.py")
                 if "resolve_always_ask_skips(" in p.read_text(encoding="utf-8")]
    assert offenders == []
