"""Attribute-first discovery, phase 2: the catalog menu-option source.

On real data (workspace 704, checked 2026-10-02) carrier values are not in
attrToVarMapping or the constraint rows -- they are menu options on the
catalog's configuration attributes ("Carrier Selection" ->
"ATT/FIRSTNET = ATT/FirstNet (provided by Motorola)"). menu_source.py
searches those options per ingested product family.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aryx.cpq.attribute_search import menu_source
from aryx.cpq.attribute_search.menu_source import option_matches, search_menu_options
from aryx.cpq.state import ConfigAttr, MenuOption

_MARKER = "aryx.cpq.data_table.data_table_cache._current_invalidation_marker"


@pytest.fixture(autouse=True)
def _fresh_cache():
    """Empty snapshot cache and a fixed re-ingest marker (no DB) per test."""
    menu_source.clear_menu_cache()
    with patch(_MARKER, return_value=1.0):
        yield
    menu_source.clear_menu_cache()


def _attr(vn: str, label: str, options: list[tuple[str, str]]) -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name=vn, display_label=label, required=False,
        default_value="", options=[MenuOption(item_value=v, display_name=d) for v, d in options],
    )


_ASTRO = [
    _attr("carrierSelectionMultiSelect_astro", "Carrier Selection", [
        ("ATT/FIRSTNET", "ATT/FirstNet (provided by Motorola)"),
        ("VERIZON", "Verizon Priority & Preemption (provided by Motorola)"),
    ]),
    _attr("wirelessCarrier_astro", "Wireless Carrier", [
        ("ATT/FIRSTNET", "ATT/FirstNet (provided by Motorola)"),
    ]),
    _attr("carrierSelectionErrorMessage_astro", "carrierSelectionErrorMessage_astro", []),
    _attr("batteryType_astro", "Battery Type", [("BATT1", "Battery 1")]),
]
_VIDEO = [_attr("cameraType_v", "Camera Type", [("C1", "Camera 1")])]


def _engine(families=("aSTRO25_bom", "videoSolutions_BOM")):
    eng = MagicMock()
    eng.list_ingested_families.return_value = list(families)
    by_family = {"aSTRO25_bom": _ASTRO, "videoSolutions_BOM": _VIDEO}
    eng.load_product_config.side_effect = lambda rd, ws, fam: (by_family[fam], fam)
    return eng


def test_option_match_is_word_bounded_and_case_insensitive():
    opt = MenuOption(item_value="ATT/FIRSTNET", display_name="ATT/FirstNet (provided by Motorola)")
    assert option_matches(opt, ["att"])
    assert option_matches(opt, ["FirstNet"])
    assert not option_matches(MenuOption(item_value="BATT1", display_name="Battery 1"), ["ATT"])


def test_finds_family_offering_the_value_under_every_grounded_label():
    hits, labels = search_menu_options("carrier", "ATT", reader=object(), engine=_engine(),
                                       workspace_id=704)
    assert labels == ["Carrier Selection", "Wireless Carrier"]
    assert [h["model"] for h in hits] == ["aSTRO25_bom", "aSTRO25_bom"]
    assert {h["attribute"] for h in hits} == {
        "carrierSelectionMultiSelect_astro", "wirelessCarrier_astro"}
    assert all(h["value"] == "ATT/FirstNet (provided by Motorola)" for h in hits)


def test_punctuated_value_spelling_still_matches():
    hits, _ = search_menu_options("carrier", "AT&T", reader=object(), engine=_engine(),
                                  workspace_id=704)
    assert {h["model"] for h in hits} == {"aSTRO25_bom"}


def test_label_only_returns_every_option_of_the_grounded_attributes():
    hits, _ = search_menu_options("carrier selection", None, reader=object(), engine=_engine(),
                                  workspace_id=704)
    assert sorted(h["value"] for h in hits) == [
        "ATT/FirstNet (provided by Motorola)",
        "Verizon Priority & Preemption (provided by Motorola)",
    ]


def test_unmatched_phrase_returns_nothing():
    hits, labels = search_menu_options("colour", "red", reader=object(), engine=_engine(),
                                       workspace_id=704)
    assert (hits, labels) == ([], [])


def test_family_that_fails_to_load_is_skipped():
    eng = _engine()
    eng.load_product_config.side_effect = lambda rd, ws, fam: (
        (_ASTRO, fam) if fam == "aSTRO25_bom" else (_ for _ in ()).throw(RuntimeError("boom"))
    )
    hits, _ = search_menu_options("carrier", "ATT", reader=object(), engine=eng, workspace_id=704)
    assert {h["model"] for h in hits} == {"aSTRO25_bom"}


def test_no_engine_or_reader_means_no_menu_search():
    assert search_menu_options("carrier", "ATT", reader=None, engine=None,
                               workspace_id=704) == ([], [])


def test_family_snapshot_is_cached_across_searches():
    eng = _engine()
    search_menu_options("carrier", "ATT", reader=object(), engine=eng, workspace_id=704)
    search_menu_options("carrier", "Verizon", reader=object(), engine=eng, workspace_id=704)
    assert eng.load_product_config.call_count == 2  # once per family, not per search


def test_cache_is_per_workspace():
    eng = _engine()
    search_menu_options("carrier", "ATT", reader=object(), engine=eng, workspace_id=704)
    search_menu_options("carrier", "ATT", reader=object(), engine=eng, workspace_id=705)
    assert eng.load_product_config.call_count == 4


def test_reingest_marker_change_clears_the_cache():
    eng = _engine()
    search_menu_options("carrier", "ATT", reader=object(), engine=eng, workspace_id=704)
    with patch(_MARKER, return_value=2.0):
        search_menu_options("carrier", "ATT", reader=object(), engine=eng, workspace_id=704)
    assert eng.load_product_config.call_count == 4


def test_snapshots_stay_cached_for_hours_not_minutes():
    """Freshness comes from the re-ingest marker, so an idle chat stays warm."""
    eng = _engine()
    with patch.object(menu_source.time, "monotonic", return_value=1000.0):
        search_menu_options("carrier", "ATT", reader=object(), engine=eng, workspace_id=704)
    with patch.object(menu_source.time, "monotonic", return_value=1000.0 + 301):
        search_menu_options("carrier", "ATT", reader=object(), engine=eng, workspace_id=704)
    assert eng.load_product_config.call_count == 2
    with patch.object(menu_source.time, "monotonic", return_value=1000.0 + 6 * 3600 + 1):
        search_menu_options("carrier", "ATT", reader=object(), engine=eng, workspace_id=704)
    assert eng.load_product_config.call_count == 4


def test_failed_family_load_is_not_retried_for_a_minute():
    eng = _engine(families=("aSTRO25_bom",))
    eng.load_product_config.side_effect = [RuntimeError("boom"), (_ASTRO, "aSTRO25_bom")]
    with patch.object(menu_source.time, "monotonic", return_value=1000.0):
        first, _ = search_menu_options("carrier", "ATT", reader=object(), engine=eng,
                                       workspace_id=704)
    with patch.object(menu_source.time, "monotonic", return_value=1030.0):
        again, _ = search_menu_options("carrier", "ATT", reader=object(), engine=eng,
                                       workspace_id=704)
    assert first == again == [] and eng.load_product_config.call_count == 1
    with patch.object(menu_source.time, "monotonic", return_value=1061.0):
        later, _ = search_menu_options("carrier", "ATT", reader=object(), engine=eng,
                                       workspace_id=704)
    assert {h["model"] for h in later} == {"aSTRO25_bom"}


# ── yes/no (boolean) attributes ──────────────────────────────────────────────


def _bool(vn: str, label: str, hidden: bool = False) -> ConfigAttr:
    return ConfigAttr(entity_id=1, variable_name=vn, display_label=label, required=False,
                      default_value="false", options=[], select_type="boolean", hidden=hidden)


_BOOL_FAMILY = [
    _bool("dualSim_astro", "Enable Dual Active Sim?"),
    _bool("spare_astro", "Include a Spare Battery with each body camera"),
    _bool("isItemSpare_astro", "Is Item Type SVX Video RSM Spare Battery"),
    _bool("boolContinue1", "BoolContinue1"),
    _bool("bulkAdd", "Bulk Add Flag", hidden=True),
    _attr("batteryType_astro", "Battery Type", [("STD", "Standard Battery")]),
]


def _bool_engine():
    eng = MagicMock()
    eng.list_ingested_families.return_value = ["aSTRO25_bom"]
    eng.load_product_config.side_effect = lambda rd, ws, fam: (_BOOL_FAMILY, fam)
    return eng


def _search(phrase, value):
    return search_menu_options(phrase, value, reader=object(), engine=_bool_engine(),
                               workspace_id=704)


def test_boolean_feature_with_no_value_is_a_yes_hit():
    hits, labels = _search("dual active sim", None)
    assert labels == ["Enable Dual Active Sim?"]
    assert hits == [{"model": "aSTRO25_bom", "base_model": None, "attribute": "dualSim_astro",
                     "value": "Yes", "label": "Enable Dual Active Sim?", "kind": "boolean",
                     "item_value": "true", "select_type": "boolean"}]


def test_boolean_feature_accepts_yes_and_no_words():
    assert [h["value"] for h in _search("dual active sim", "enabled")[0]] == ["Yes"]
    assert [h["value"] for h in _search("dual active sim", "no")[0]] == ["No"]


def test_boolean_feature_ignores_non_yes_no_values():
    assert _search("dual active sim", "ATT")[0] == []


def test_is_prefixed_predicate_flags_are_not_searchable():
    hits, labels = _search("spare battery", None)
    assert labels == ["Include a Spare Battery with each body camera"]
    assert [h["attribute"] for h in hits] == ["spare_astro"]


def test_single_word_and_hidden_boolean_flags_are_not_searchable():
    assert _search("boolcontinue1", None) == ([], [])
    assert _search("bulk add flag", None) == ([], [])


def test_option_attributes_still_tagged_as_options():
    hits, _ = _search("battery type", "standard")
    assert [h["kind"] for h in hits] == ["option"]


def test_camelcase_is_predicates_and_flag_labels_are_not_searchable():
    fam = [_bool("x", "isRelatedServiceCategoryAryDEVICE PROGRAMMING"),
           _bool("y", "BOM Optimize Flag")]
    eng = _bool_engine()
    eng.load_product_config.side_effect = lambda rd, ws, f: (fam, f)
    assert search_menu_options("device programming", None, reader=object(), engine=eng,
                               workspace_id=1) == ([], [])
    assert search_menu_options("bom optimize", None, reader=object(), engine=eng,
                               workspace_id=1) == ([], [])


def test_attribute_with_only_yes_no_options_is_a_feature():
    fam = [_attr("spareRadio", 'Is this a "SPARE radio"', [("Yes", "Yes"), ("No", "No")])]
    eng = _bool_engine()
    eng.load_product_config.side_effect = lambda rd, ws, f: (fam, f)
    hits, _ = search_menu_options("spare radio", None, reader=object(), engine=eng,
                                  workspace_id=1)
    assert [(h["value"], h["kind"]) for h in hits] == [("Yes", "boolean")]


def test_hidden_option_attributes_are_not_searchable():
    hidden = _attr("internalList", "Internal Carrier List", [("ATT", "ATT")])
    hidden.hidden = True
    eng = _bool_engine()
    eng.load_product_config.side_effect = lambda rd, ws, f: ([hidden], f)
    assert search_menu_options("carrier list", "ATT", reader=object(), engine=eng,
                               workspace_id=1) == ([], [])


def test_grounding_picks_the_best_label_across_all_families():
    loose = [_attr("dataCable", "Data Cable", [("Y", "Yes"), ("N", "No")])]
    exact = [_bool("usbc", "Include USB-C Data and Charge Cable in-box")]
    eng = MagicMock()
    eng.list_ingested_families.return_value = ["A", "B"]
    eng.load_product_config.side_effect = lambda rd, ws, f: ((loose if f == "A" else exact), f)
    hits, labels = search_menu_options("usb-c data and charge cable", None, reader=object(),
                                       engine=eng, workspace_id=1)
    assert labels == ["Include USB-C Data and Charge Cable in-box"]
    assert [h["model"] for h in hits] == ["B"]


def test_option_hits_carry_the_code_to_store():
    hits, _ = search_menu_options("carrier selection", "ATT", reader=object(), engine=_engine(),
                                  workspace_id=704)
    assert [(h["item_value"], h["select_type"]) for h in hits] == [("ATT/FIRSTNET", "single")]


def test_no_answer_on_a_true_boolean_stores_false():
    assert [h["item_value"] for h in _search("dual active sim", "no")[0]] == ["false"]


def test_yes_no_menu_stores_its_own_yes_code():
    fam = [_attr("spareRadio", 'Is this a "SPARE radio"', [("Y1", "Yes"), ("N1", "No")])]
    eng = _bool_engine()
    eng.load_product_config.side_effect = lambda rd, ws, f: (fam, f)
    hits, _ = search_menu_options("spare radio", None, reader=object(), engine=eng, workspace_id=1)
    assert [h["item_value"] for h in hits] == ["Y1"]



def test_acronym_led_features_are_searchable():
    fam = [_bool("ism", "ISM Band Support"), _bool("isdn", "ISDN Line Required"),
           _bool("iso", "ISO Certified")]
    eng = _bool_engine()
    eng.load_product_config.side_effect = lambda rd, ws, f: (fam, f)
    for phrase, vn in (("ism band", "ism"), ("isdn line", "isdn"), ("iso certified", "iso")):
        hits, _ = search_menu_options(phrase, None, reader=object(), engine=eng, workspace_id=1)
        assert [h["attribute"] for h in hits] == [vn], phrase


def test_is_predicates_are_still_filtered():
    fam = [_bool("a", "Is Item Type SVX Spare"), _bool("b", "isRelatedService DEVICE"),
           _bool("c", "IS Item Type Spare")]
    eng = _bool_engine()
    eng.load_product_config.side_effect = lambda rd, ws, f: (fam, f)
    assert search_menu_options("item type spare", None, reader=object(), engine=eng,
                               workspace_id=1) == ([], [])
