"""A base model that owns the model's default configuration is derived when the Whitelist leaves 2+ (flag
`cpq_derive_base_model_default_owner_enabled`).

ws 281 / 1267, APX N70: three base models (VHF, 700/800 MHz, UHF) whose Whitelist rows each list every band, so a known
band narrows nothing and "country only" left the base model unknown (flashcode digits asked). The Defaultinattr rows
of the 700/800 MHz base model define 32 defaults (the band among them), the VHF and UHF ones 3 and 5."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq import base_model_defaults as bmd
from aryx.cpq import derive_base_model_default_owner as owner_mod
from aryx.cpq.data_table import data_table_derive_base_model as derive

BAND, KEYPAD, ANT, COUNTRY = ("modelSelectionFrequencyBands_astro", "modelSelectionKeypadType_astro",
                              "antennasType_astro", "ultimateDestinationCountry")
K, U, X = "H35KET9PW8AN", "H35UCT9PW8AN", "H35XDT9PW8AN"


def _wl(bm, attr, val):
    return {"CPQModel": "APXN70", "BaseModel": bm, "attr1": attr, "val1": val}


ROWS = [_wl(bm, BAND, band) for bm in (K, U, X) for band in ("VHF", "700/800 MHZ", "UHF")] + \
       [_wl(bm, COUNTRY, "US") for bm in (K, U, X)]


def _di(bm, **pairs):
    row = {"BaseModel": bm}
    for i, (attr, val) in enumerate(pairs.items(), start=1):
        row[f"attr{i}"], row[f"val{i}"] = attr, val
    return row


DEFAULTS = [_di(U, **{BAND: "700/800 MHZ", KEYPAD: "LIMITED KEYPAD", ANT: "STUBBY", "a_x": "1"}),
            _di(K, **{KEYPAD: "LIMITED KEYPAD", ANT: "WHIP"}), _di(X, **{KEYPAD: "LIMITED KEYPAD"})]


def _owner(filled=None, customer=(), rows=ROWS, defaults=DEFAULTS, flag=True):
    settings = SimpleNamespace(cpq_derive_base_model_default_owner_enabled=flag,
                               cpq_derive_discriminators_first_enabled=False)
    with patch.object(derive, "get_settings", return_value=settings), \
            patch.object(owner_mod, "get_settings", return_value=settings), \
            patch.object(derive, "_model_rows", return_value=rows), \
            patch.object(bmd, "_load_defaultinattr_rows", return_value=defaults):
        return owner_mod.default_owner_base_model("APXN70", {COUNTRY: "US", **(filled or {})}, 1, "p", {},
                                                  frozenset(), frozenset(customer))


def test_the_base_model_defining_the_most_defaults_is_derived():
    assert _owner() == U


def test_flag_off_derives_nothing():
    assert _owner(flag=False) is None


def test_a_customer_value_that_differs_from_its_default_blocks_it():
    """A customer who asked for another band must not be given the default band's base model."""
    assert _owner({BAND: "VHF"}, customer={BAND}) is None


def test_a_customer_value_equal_to_its_default_keeps_it():
    assert _owner({BAND: "700/800 MHz"}, customer={BAND}) == U


def test_an_engine_pick_that_differs_does_not_block_it():
    assert _owner({BAND: "VHF"}, customer=()) == U


def test_a_base_model_without_defaultinattr_rows_means_no_evidence():
    assert _owner(defaults=DEFAULTS[:2]) is None


def test_no_strict_superset_means_no_derivation():
    tied = [_di(U, **{KEYPAD: "LIMITED KEYPAD", ANT: "STUBBY"}), _di(K, **{KEYPAD: "LIMITED KEYPAD", BAND: "VHF"}),
            _di(X, **{KEYPAD: "LIMITED KEYPAD", ANT: "WHIP"})]
    assert _owner(defaults=tied) is None


def test_own_defaults_exclude_all_rows_and_are_cached():
    cache: dict = {}
    with patch.object(bmd, "_load_defaultinattr_rows", return_value=DEFAULTS + [_di("ALL", **{"z_x": "9"})]) as load:
        first = bmd.base_model_own_defaults(U.lower(), 1, "p", cache)
        assert bmd.base_model_own_defaults(U, 1, "p", cache) is first
    assert set(first) == {BAND, KEYPAD, ANT, "a_x"} and load.call_count == 1
