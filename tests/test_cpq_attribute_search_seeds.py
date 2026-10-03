"""Attribute-first discovery, phase 4: filling the matched value into a session.

seeds.py writes a matched attribute value into a CpqSession the way the
engine's own hint matching would (multi-select into filled_multi, others
into filled, source "hint" so the engine's constraint check still
re-validates it), and applies values remembered for a family once the
customer picks that family.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.attribute_search.lookup import find_products_by_attribute
from aryx.cpq.attribute_search.seeds import apply_pending_seeds, seed_values, trim_ambiguous_seeds
from aryx.cpq.state import CpqSession

_MULTI = {"vn": "carrierSel", "item_value": "ATT/FIRSTNET",
          "display": "ATT/FirstNet (provided by Motorola)", "select_type": "multi"}
_SINGLE = {"vn": "wirelessCarrier", "item_value": "ATT/FIRSTNET",
           "display": "ATT/FirstNet (provided by Motorola)", "select_type": "single"}
_BOOL = {"vn": "dualSim", "item_value": "true", "display": "Yes", "select_type": "boolean"}


def test_single_select_goes_into_filled_as_a_hint():
    s = CpqSession()
    seed_values(s, [_SINGLE])
    assert s.filled == {"wirelessCarrier": "ATT/FIRSTNET"}
    assert s.display_filled == {"wirelessCarrier": "ATT/FirstNet (provided by Motorola)"}
    assert s.filled_source == {"wirelessCarrier": "hint"}
    assert s.filled_multi == {}


def test_multi_select_goes_into_filled_multi_without_duplicates():
    s = CpqSession()
    seed_values(s, [_MULTI, _MULTI])
    assert s.filled_multi == {"carrierSel": ["ATT/FIRSTNET"]}
    assert "carrierSel" not in s.filled
    assert s.filled_source == {"carrierSel": "hint"}


def test_boolean_is_stored_as_its_code():
    s = CpqSession()
    seed_values(s, [_BOOL])
    assert s.filled == {"dualSim": "true"}


def test_seed_without_a_code_is_skipped():
    s = CpqSession()
    seed_values(s, [{"vn": "x", "item_value": "", "display": "", "select_type": "single"}])
    assert s.filled == {} and s.filled_source == {}


def test_pending_seeds_apply_for_the_chosen_family_only_and_clear():
    s = CpqSession()
    s.attribute_search_seeds = {"aSTRO25_bom": [_SINGLE], "videoSolutions_BOM": [_BOOL]}
    assert apply_pending_seeds(s, "ASTRO25_BOM") == 1
    assert s.filled == {"wirelessCarrier": "ATT/FIRSTNET"}
    assert s.attribute_search_seeds == {}


def test_pending_seeds_for_an_unoffered_family_are_dropped():
    s = CpqSession()
    s.attribute_search_seeds = {"aSTRO25_bom": [_SINGLE]}
    assert apply_pending_seeds(s, "MOTOTRBO") == 0
    assert s.filled == {} and s.attribute_search_seeds == {}


def test_seeds_survive_a_session_round_trip():
    s = CpqSession()
    s.attribute_search_seeds = {"aSTRO25_bom": [_MULTI]}
    s.pending_attribute_label = "carrier"
    back = CpqSession.from_dict(s.to_dict())
    assert back.attribute_search_seeds == {"aSTRO25_bom": [_MULTI]}
    assert back.pending_attribute_label == "carrier"


def test_lookup_collects_seeds_per_family_from_menu_hits():
    menu = [
        {"model": "aSTRO25_bom", "base_model": None, "attribute": "carrierSel", "label": "Carrier Selection",
         "value": "ATT/FirstNet (provided by Motorola)", "kind": "option",
         "item_value": "ATT/FIRSTNET", "select_type": "multi"},
        {"model": "aSTRO25_bom", "base_model": None, "attribute": "wirelessCarrier", "label": "Wireless Carrier",
         "value": "ATT/FirstNet (provided by Motorola)", "kind": "option",
         "item_value": "ATT/FIRSTNET", "select_type": "single"},
    ]
    with patch("aryx.cpq.attribute_search.lookup.list_attribute_role_labels", return_value=[]), \
         patch("aryx.cpq.attribute_search.lookup.search_menu_options",
               return_value=(menu, ["Carrier Selection", "Wireless Carrier"])):
        res = find_products_by_attribute("carrier", "ATT", workspace_id=1, reader=object(),
                                         engine=object())
    assert res.products[0]["seeds"] == [
        {"vn": "carrierSel", "item_value": "ATT/FIRSTNET",
         "display": "ATT/FirstNet (provided by Motorola)", "select_type": "multi", "kind": "option"},
        {"vn": "wirelessCarrier", "item_value": "ATT/FIRSTNET",
         "display": "ATT/FirstNet (provided by Motorola)", "select_type": "single", "kind": "option"},
    ]


def _yes(vn: str) -> dict:
    return {"vn": vn, "item_value": "true", "display": "Yes", "select_type": "boolean",
            "kind": "boolean"}


def test_value_matched_seeds_are_all_kept():
    seeds = [dict(_MULTI, kind="option"), dict(_SINGLE, kind="option")]
    assert trim_ambiguous_seeds(seeds) == seeds


def test_a_single_yes_no_feature_is_kept():
    assert trim_ambiguous_seeds([_yes("dualSim")]) == [_yes("dualSim")]


def test_several_yes_no_features_are_dropped_as_ambiguous():
    seeds = [_yes("includeSpare"), _yes("isSpareRadioBatt"), _yes("isSpareRadioAntenna")]
    assert trim_ambiguous_seeds(seeds) == []


def test_dropping_ambiguous_features_keeps_value_matched_seeds():
    opt = dict(_SINGLE, kind="option")
    assert trim_ambiguous_seeds([opt, _yes("a"), _yes("b")]) == [opt]


def test_family_with_ambiguous_features_is_still_offered_without_values():
    menu = [
        {"model": "aSTRO25_bom", "base_model": None, "attribute": vn, "label": label,
         "value": "Yes", "kind": "boolean", "item_value": "true", "select_type": "boolean"}
        for vn, label in (("includeSpare", "Include a Spare?"),
                          ("isSpareRadio", 'Is this a "SPARE radio"'))
    ]
    with patch("aryx.cpq.attribute_search.lookup.list_attribute_role_labels", return_value=[]), \
         patch("aryx.cpq.attribute_search.lookup.search_menu_options",
               return_value=(menu, ["Include a Spare?", 'Is this a "SPARE radio"'])):
        res = find_products_by_attribute("spare", None, workspace_id=1, reader=object(),
                                         engine=object())
    assert res.products[0]["seeds"] == []
    assert res.products[0]["sources"] == ["catalog_menu"]
