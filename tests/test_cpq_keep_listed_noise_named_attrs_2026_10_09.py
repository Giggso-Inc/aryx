"""An attribute whose name contains a noise fragment is kept when the catalog's AttrSequence lists it (flag
`cpq_keep_listed_noise_named_attrs_enabled`).

ws 281, APX N50: ``documentationTestResultsRatedAudioPrintoutLabel_astro`` contains "test" and was dropped like a
``TestPager``; 1 of the 21 attributes dropped by name is listed in N50's sequence, the rest are listed nowhere."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq.product_config import product_config_listed_names as listed_mod
from aryx.cpq.product_config.product_config_attrs import build_config_attrs
from aryx.cpq.product_config.product_config_lookups import ArraySetLookups

REAL, NOISE, PLAIN = "documentationTestResultsRatedAudioPrintoutLabel_astro", "testPager", "antennasType_astro"


def _ents(*names):
    ents = [{"id": i, "type": "X", "name": n} for i, n in enumerate(names, start=1)]
    pgs = {i: {"variable_name": n, "status": "1", "hidden": "0"} for i, n in enumerate(names, start=1)}
    return ents, pgs


def _build(names, listed):
    ents, pgs = _ents(*names)
    engine = SimpleNamespace(_is_layout_noise=lambda _t: False)
    arrays = ArraySetLookups()
    return [a.variable_name for a in build_config_attrs(engine, ents, pgs, {}, arrays, set(), listed)]


def test_today_the_name_filter_drops_the_real_attribute_too():
    assert _build([REAL, NOISE, PLAIN], frozenset()) == [PLAIN]


def test_a_noise_named_attribute_the_sequence_lists_is_kept_and_true_noise_still_goes():
    assert _build([REAL, NOISE, PLAIN], frozenset({REAL})) == [REAL, PLAIN]


def _rows(*names):
    return ([], [{"AttrName": n} for n in names], None, None, None)


def test_the_names_come_from_the_sequence_table():
    settings = SimpleNamespace(cpq_keep_listed_noise_named_attrs_enabled=True)
    with patch.object(listed_mod, "get_settings", return_value=settings), \
            patch.object(listed_mod, "_load_all_tables", return_value=_rows(REAL, "", PLAIN)):
        assert listed_mod.listed_attr_names(1, "p") == {REAL, PLAIN}


def test_flag_off_no_workspace_or_a_failing_table_gives_nothing():
    off = SimpleNamespace(cpq_keep_listed_noise_named_attrs_enabled=False)
    on = SimpleNamespace(cpq_keep_listed_noise_named_attrs_enabled=True)
    with patch.object(listed_mod, "get_settings", return_value=off), \
            patch.object(listed_mod, "_load_all_tables", return_value=_rows(REAL)):
        assert listed_mod.listed_attr_names(1, "p") == frozenset()
    with patch.object(listed_mod, "get_settings", return_value=on):
        assert listed_mod.listed_attr_names(None, "p") == frozenset()
        with patch.object(listed_mod, "_load_all_tables", side_effect=RuntimeError("db")):
            assert listed_mod.listed_attr_names(1, "p") == frozenset()


# --- options: a noise word inside a real option name ---------------------------------------------------------------
def _noise(iv, flag):
    from aryx.cpq.product_config import product_config_menu_build as mb

    settings = SimpleNamespace(cpq_noise_option_whole_value_enabled=flag)
    with patch.object(mb, "get_settings", return_value=settings):
        return mb._is_noise_option(iv.lower(), iv.lower())


def test_today_a_real_option_with_the_word_test_is_dropped():
    assert _noise("FPS APX TEST TRIGGER - SW VALIDATION", flag=False)
    assert _noise("TEST RESULTS/RATED AUDIO PRINTOUT LABEL", flag=False)


def test_with_the_flag_only_a_whole_placeholder_value_is_noise():
    assert not _noise("FPS APX TEST TRIGGER - SW VALIDATION", flag=True)
    assert not _noise("TEST RESULTS/RATED AUDIO PRINTOUT LABEL", flag=True)
    assert not _noise("LATEST RELEASE", flag=True)
    for placeholder in ("Test", "dummy", "Pager", "Test 1", "dummy_2"):
        assert _noise(placeholder, flag=True), placeholder
