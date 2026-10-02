"""Attribute-first discovery, phase 2: grounding + Data Table lookup.

ground.py maps the raw phrase the router extracted ("carrier") onto the
catalog's real attrToVarMapping labels ("Carrier Selection"); lookup.py
searches the Data Table under every grounded label and groups the hits by
model.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.attribute_search.ground import ground_attribute_label, value_variants
from aryx.cpq.attribute_search.lookup import find_products_by_attribute

_LOOKUP = "aryx.cpq.attribute_search.lookup"
_LABELS = ["Carrier Selection", "Wireless Carrier", "Feature Type", "Region", "Base Model"]


# ── ground_attribute_label ───────────────────────────────────────────────────


def test_exact_label_wins_over_partial_matches():
    assert ground_attribute_label("feature type", _LABELS) == ["Feature Type"]


def test_single_word_matches_every_label_containing_it():
    assert ground_attribute_label("carrier", _LABELS) == ["Carrier Selection", "Wireless Carrier"]


def test_plural_and_case_are_ignored():
    assert ground_attribute_label("CARRIERS", _LABELS) == ["Carrier Selection", "Wireless Carrier"]


def test_full_phrase_prefers_the_exact_label():
    assert ground_attribute_label("carrier selection", _LABELS) == ["Carrier Selection"]


def test_filler_words_are_ignored():
    assert ground_attribute_label("the region", _LABELS) == ["Region"]


def test_more_specific_phrase_falls_back_to_contained_label():
    assert ground_attribute_label("region code", ["Region", "Carrier Selection"]) == ["Region"]


def test_unrelated_phrase_grounds_to_nothing():
    assert ground_attribute_label("colour", _LABELS) == []


def test_empty_inputs_ground_to_nothing():
    assert ground_attribute_label("", _LABELS) == []
    assert ground_attribute_label("carrier", []) == []


def test_value_variants_add_punctuation_free_spelling():
    assert value_variants("AT&T") == ["AT&T", "ATT"]
    assert value_variants(" ATT ") == ["ATT"]
    assert value_variants("") == []


# ── find_products_by_attribute ───────────────────────────────────────────────


def _rows_by_label(label, value, workspace_id, catalog_prefix="", cache=None):
    table = {
        "Carrier Selection": [
            {"model": "APX1000", "base_model": "H45", "attribute": "carrierSel_astro",
             "value": "ATT/FIRSTNET"},
            {"model": "APX1000", "base_model": "H46", "attribute": "carrierSel_astro",
             "value": "ATT/FIRSTNET"},
            {"model": "APX8000", "base_model": "H90", "attribute": "carrierSel_astro",
             "value": "VERIZON"},
        ],
        "Wireless Carrier": [
            {"model": "APXNEXT", "base_model": "N1", "attribute": "wirelessCarrier_astro",
             "value": "ATT"},
        ],
    }
    v = (value or "").casefold()
    return [r for r in table.get(label, []) if v in r["value"].casefold()]


def _patched():
    return (
        patch(f"{_LOOKUP}.list_attribute_role_labels", return_value=_LABELS),
        patch(f"{_LOOKUP}.search_products_by_feature", side_effect=_rows_by_label),
    )


def test_lookup_returns_none_when_label_does_not_ground():
    p1, p2 = _patched()
    with p1, p2 as search:
        assert find_products_by_attribute("colour", "red", workspace_id=1) is None
    search.assert_not_called()


def test_lookup_groups_hits_by_model_across_labels():
    p1, p2 = _patched()
    with p1, p2:
        res = find_products_by_attribute("carrier", "ATT", workspace_id=1)
    assert res.labels == ["Carrier Selection", "Wireless Carrier"]
    assert [p["model"] for p in res.products] == ["APX1000", "APXNEXT"]
    apx = res.products[0]
    assert apx["base_models"] == ["H45", "H46"]
    assert apx["values"] == ["ATT/FIRSTNET"]
    assert apx["labels"] == ["Carrier Selection"]


def test_lookup_tries_punctuation_free_value_spelling():
    p1, p2 = _patched()
    with p1, p2:
        res = find_products_by_attribute("carrier", "AT&T", workspace_id=1)
    assert [p["model"] for p in res.products] == ["APX1000", "APXNEXT"]


def test_lookup_with_no_matching_value_returns_empty_products():
    p1, p2 = _patched()
    with p1, p2:
        res = find_products_by_attribute("carrier", "T-Mobile", workspace_id=1)
    assert res.labels == ["Carrier Selection", "Wireless Carrier"]
    assert res.products == []


def test_label_only_lookup_lists_offered_values():
    p1, p2 = _patched()
    with p1, p2:
        res = find_products_by_attribute("carrier", None, workspace_id=1)
    assert res.value is None
    assert res.offered_values == ["ATT", "ATT/FIRSTNET", "VERIZON"]
    assert [p["model"] for p in res.products] == ["APX1000", "APX8000", "APXNEXT"]


def test_lookup_shares_one_cache_dict_across_calls():
    p1, p2 = _patched()
    with p1 as labels, p2 as search:
        find_products_by_attribute("carrier", "ATT", workspace_id=7)
    cache = labels.call_args.kwargs["cache"]
    assert all(c.kwargs["cache"] is cache for c in search.call_args_list)
    assert all(c.args[2] == 7 for c in search.call_args_list)


def test_feature_only_when_every_hit_is_a_yes_no_attribute():
    menu = [{"model": "aSTRO25_bom", "base_model": None, "attribute": "dualSim_astro",
             "value": "Yes", "label": "Enable Dual Active Sim?", "kind": "boolean"}]
    with patch(f"{_LOOKUP}.list_attribute_role_labels", return_value=[]), \
         patch(f"{_LOOKUP}.search_menu_options", return_value=(menu, ["Enable Dual Active Sim?"])):
        res = find_products_by_attribute("dual active sim", None, workspace_id=1,
                                         reader=object(), engine=object())
    assert res.feature_only is True
    assert [p["model"] for p in res.products] == ["aSTRO25_bom"]


def test_not_feature_only_when_option_hits_are_mixed_in():
    menu = [
        {"model": "F", "base_model": None, "attribute": "a", "value": "Yes",
         "label": "Spare Battery", "kind": "boolean"},
        {"model": "F", "base_model": None, "attribute": "b", "value": "Whip",
         "label": "Spare Antenna", "kind": "option"},
    ]
    with patch(f"{_LOOKUP}.list_attribute_role_labels", return_value=[]), \
         patch(f"{_LOOKUP}.search_menu_options",
               return_value=(menu, ["Spare Antenna", "Spare Battery"])):
        res = find_products_by_attribute("spare", None, workspace_id=1, reader=object(),
                                         engine=object())
    assert res.feature_only is False


def test_loose_data_table_label_loses_to_an_exact_menu_label():
    menu = [{"model": "videoSolutions_BOM", "base_model": None, "attribute": "usbc",
             "value": "Yes", "label": "Include USB-C Data and Charge Cable in-box",
             "kind": "boolean"}]
    dt_row = {"model": "APX1000", "base_model": "H1", "attribute": "dataCable", "value": "Yes"}
    with patch(f"{_LOOKUP}.list_attribute_role_labels", return_value=["Data Cable"]), \
         patch(f"{_LOOKUP}.search_products_by_feature", return_value=[dt_row]), \
         patch(f"{_LOOKUP}.search_menu_options",
               return_value=(menu, ["Include USB-C Data and Charge Cable in-box"])):
        res = find_products_by_attribute("usb-c data and charge cable", None, workspace_id=1,
                                         reader=object(), engine=object())
    assert res.labels == ["Include USB-C Data and Charge Cable in-box"]
    assert [p["model"] for p in res.products] == ["videoSolutions_BOM"]
    assert res.feature_only is True
