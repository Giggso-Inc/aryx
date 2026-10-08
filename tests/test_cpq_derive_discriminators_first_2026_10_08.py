"""Apply the attributes that separate a model's base models before the weaker ones (flag
`cpq_derive_discriminators_first_enabled`).

ws 1267, APX 900, real shape of the whitelist rows: every base model holds one frequency band and one keypad type
(attr1 / attr2), eight of them list countries including US, and the two 700/800 MHz base models only mention a country
inside another attribute's conditional row (housing GREEN ... country BR). Country US applied first dropped those two
(10 -> 8), the 700/800 MHz answer then matched nothing, and the base model stayed ambiguous."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq.data_table import data_table_derive_base_model as derive

FREQ, KEYPAD = "modelSelectionFrequencyBands_astro", "modelSelectionKeypadType_astro"
COUNTRY, HOUSING, REGION = "ultimateDestinationCountry", "modelSelectionHousing_astro", "modelSelectionRegion_astro"
FEATURE = "systemEnhancementFeatureType_astro"
BANDS = {"K": "VHF", "Q": "UHF R1", "S": "UHF R2", "U": "700/800 MHZ", "W": "900 MHZ"}
KEYPADS = {"F": "LIMITED KEYPAD", "H": "FULL KEYPAD"}
CODES = {f"H92{b}D{k}9PW{'6' if k == 'F' else '7'}AN": (BANDS[b], KEYPADS[k]) for b in BANDS for k in KEYPADS}
U_F = "H92UDF9PW6AN"


def _rows():
    """The real shape: band / keypad / region are the targets and conditions of every base model's rows; country is only
    ever a condition of OTHER attributes' rows (US on the K/Q/S/W base models, BR and MX on the two 700/800 ones)."""
    rows = []
    for code, (band, keypad) in CODES.items():
        rows.append({"CPQModel": "APX900", "BaseModel": code, "attr1": FREQ, "val1": band,
                     "attr2": KEYPAD, "val2": keypad, "attr3": REGION, "val3": "NA"})
        rows.append({"CPQModel": "APX900", "BaseModel": code, "attr1": FEATURE, "val1": "FRONT PANEL",
                     "attr2": "customerType", "val2": "FEDERAL"})          # several feature values: not separating
        if band == "700/800 MHZ":
            rows.append({"CPQModel": "APX900", "BaseModel": code, "attr1": HOUSING, "val1": "GREEN",
                         "attr2": COUNTRY, "val2": "BR"})
            rows.append({"CPQModel": "APX900", "BaseModel": code, "attr1": FEATURE, "val1": "TACTICAL",
                         "attr2": COUNTRY, "val2": "MX"})
        else:
            rows.append({"CPQModel": "APX900", "BaseModel": code, "attr1": FEATURE, "val1": "DELETE NARROWBANDING",
                         "attr2": COUNTRY, "val2": "US"})
    return rows


def _narrow(known, flag):
    settings = SimpleNamespace(cpq_derive_discriminators_first_enabled=flag)
    with patch.object(derive, "get_settings", return_value=settings):
        return derive.narrowed_base_models(_rows(), known)


# the order the live run applied them in: country first, then the answers
ANSWERS = {COUNTRY: "US", FREQ: "700/800 MHz", KEYPAD: "Limited Keypad"}


def test_today_country_first_drops_the_700_800_base_models_and_the_answers_stay_ambiguous():
    assert len(_narrow(ANSWERS, flag=False)) == 4          # the 4 limited-keypad base models still in play


def test_with_the_flag_the_band_and_keypad_answers_are_applied_first_and_one_base_model_is_left():
    left = _narrow(ANSWERS, flag=True)
    assert left == {code for code, (band, keypad) in CODES.items() if (band, keypad) == ("700/800 MHZ", "LIMITED KEYPAD")}


def test_country_alone_no_longer_excludes_base_models_it_is_only_a_condition_for():
    assert len(_narrow({COUNTRY: "US"}, flag=False)) == 8          # today: the two 700/800 base models are dropped
    assert len(_narrow({COUNTRY: "US"}, flag=True)) == 10          # flag: nothing is excluded by it
    assert len(_narrow({FREQ: "VHF"}, flag=True)) == 2


def test_an_attribute_the_rows_use_as_a_target_still_narrows():
    rows = _rows() + [{"CPQModel": "APX900", "BaseModel": "H92KDF9PW6AN", "attr1": HOUSING, "val1": "BLACK"}]
    settings = SimpleNamespace(cpq_derive_discriminators_first_enabled=True)
    with patch.object(derive, "get_settings", return_value=settings):
        left = derive.narrowed_base_models(rows, {HOUSING: "GREEN"})
    assert "H92KDF9PW6AN" not in left and len(left) == 9              # it has housing rows and none says GREEN


def test_the_separating_attributes_are_the_two_every_base_model_holds_one_value_of():
    assert set(derive.single_valued_discriminators(_rows(), set(CODES))) == {FREQ, KEYPAD}


def test_the_explanation_replays_the_same_order():
    settings = SimpleNamespace(cpq_derive_discriminators_first_enabled=True)
    with patch.object(derive, "get_settings", return_value=settings), \
            patch.object(derive, "_model_rows", return_value=_rows()):
        report = derive.explain_known_attrs("APX900", ANSWERS, 1267)
    assert {e["attr"]: e["applied_order"] for e in report} == {FREQ: 0, KEYPAD: 1}
