"""Two ws 1267 fixes.

* Noise filter: `documentationTestResultsRatedAudioPrintoutLabel_astro` contains "test" and has no AttrSequence row, so
  it was dropped as noise although every stored layout places it. With cpq_keep_listed_noise_named_attrs_enabled the
  names any stored layout places now count as listed.
* Blind pick: the optional multi-select Feature Type on APX N30 was blind-picked ("Disable Cloud Services");
  cpq_no_blind_fill_optional_multi_enabled extends the optional no-blind-fill guard to multi-selects.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq.auto_fill_stages import optional_blind_guard
from aryx.cpq.product_config import product_config_listed_names as listed

TEST_LABEL = "documentationTestResultsRatedAudioPrintoutLabel_astro"


class _Engine:
    def __init__(self, by_variant):
        self.by_variant = by_variant

    def _load_layout_components(self, ws, prefix, source, variant="__default__"):
        return self.by_variant.get(variant)


def _settings(**flags):
    return SimpleNamespace(**flags)


def test_layout_listed_noise_name_is_kept():
    engine = _Engine({"__default__": [{"resourceAttributeVarName": "antennasType_astro"}],
                      "portable": [{"resourceAttributeVarName": TEST_LABEL}, {"label": "no var"}]})
    with patch.object(listed, "get_settings", return_value=_settings(cpq_keep_listed_noise_named_attrs_enabled=True)), \
         patch.object(listed, "_sequence_names", return_value=set()), \
         patch("aryx.cpq.layout_and_join_data.layout_variant.stored_variant_keys", return_value=["portable"]), \
         patch("aryx.cpq.layout_source.DEFAULT_LAYOUT_VARIANT", "__default__"):
        names = listed.listed_attr_names(1267, "astro", engine)
    assert TEST_LABEL in names and "antennasType_astro" in names and "" not in names


def test_without_engine_only_the_sequence_counts():
    with patch.object(listed, "get_settings", return_value=_settings(cpq_keep_listed_noise_named_attrs_enabled=True)), \
         patch.object(listed, "_sequence_names", return_value={"seqAttr"}):
        assert listed.listed_attr_names(1267, "astro") == frozenset({"seqAttr"})


def test_flag_off_lists_nothing():
    with patch.object(listed, "get_settings", return_value=_settings(cpq_keep_listed_noise_named_attrs_enabled=False)):
        assert listed.listed_attr_names(1267, "astro", _Engine({})) == frozenset()


def test_layout_failure_keeps_the_sequence_names():
    class Broken:
        def _load_layout_components(self, *a):
            raise RuntimeError("boom")

    with patch.object(listed, "get_settings", return_value=_settings(cpq_keep_listed_noise_named_attrs_enabled=True)), \
         patch.object(listed, "_sequence_names", return_value={"seqAttr"}):
        assert listed.listed_attr_names(1267, "astro", Broken()) == frozenset({"seqAttr"})


def _attr(select_type, required=False):
    return SimpleNamespace(select_type=select_type, required=required)


STATE = SimpleNamespace(is_decision_attr=False)


def test_multi_select_still_blind_picked_without_the_new_flag():
    with patch.object(optional_blind_guard, "get_settings", return_value=_settings(cpq_no_blind_fill_optional_enabled=True)):
        assert optional_blind_guard.optional_without_basis(_attr("multi"), STATE) is False
        assert optional_blind_guard.optional_without_basis(_attr("single"), STATE) is True


def test_multi_select_left_open_with_the_new_flag():
    s = _settings(cpq_no_blind_fill_optional_enabled=True, cpq_no_blind_fill_optional_multi_enabled=True)
    with patch.object(optional_blind_guard, "get_settings", return_value=s):
        assert optional_blind_guard.optional_without_basis(_attr("multi"), STATE) is True
        assert optional_blind_guard.optional_without_basis(_attr("multi", required=True), STATE) is False
        assert optional_blind_guard.optional_without_basis(_attr("multi"), SimpleNamespace(is_decision_attr=True)) is False


def test_multi_flag_alone_does_nothing():
    s = _settings(cpq_no_blind_fill_optional_enabled=False, cpq_no_blind_fill_optional_multi_enabled=True)
    with patch.object(optional_blind_guard, "get_settings", return_value=s):
        assert optional_blind_guard.optional_without_basis(_attr("multi"), STATE) is False
