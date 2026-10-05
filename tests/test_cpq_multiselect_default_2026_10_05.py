"""Plan F11: several Defaultinattr rows for one multi-select attribute are its
pre-checked set. Flag `cpq_multiselect_default_enabled`; synthetic names only.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.cpq.data_table import data_table_defaultinattr as dd
from aryx.cpq.data_table_bridge import conflicts as conf
from aryx.cpq.state import MenuOption


def _cfg(**kw):
    m = MagicMock()
    for k, v in kw.items():
        setattr(m.return_value, k, v)
    return m


def _rows(*pairs):
    return [{"BaseModel": bm, "attr1": attr, "val1": val} for bm, attr, val in pairs]


def _values(rows, base_model="BM1", attr="multi_vn"):
    with patch.object(dd, "_load_defaultinattr_rows", return_value=rows):
        return dd.resolve_defaultinattr_values(base_model, attr, 1)


def test_all_default_rows_of_the_base_model_are_returned_sorted():
    rows = _rows(("BM1", "multi_vn", "VHF"), ("BM1", "multi_vn", "UHF"), ("BM1", "multi_vn", "700"),
                 ("BM2", "multi_vn", "OTHER"), ("BM1", "other_vn", "X"))
    assert _values(rows) == ["700", "UHF", "VHF"]


def test_exact_base_model_beats_all_and_all_is_the_fallback():
    rows = _rows(("ALL", "multi_vn", "G1"), ("ALL", "multi_vn", "G2"), ("BM1", "multi_vn", "E1"))
    assert _values(rows) == ["E1"]
    assert _values(rows, base_model="BM9") == ["G1", "G2"]
    assert _values(rows, base_model="") == [] and _values(rows, attr="") == []


def test_single_value_reader_still_treats_two_values_as_ambiguous():
    rows = _rows(("BM1", "multi_vn", "A"), ("BM1", "multi_vn", "B"))
    with patch.object(dd, "_load_defaultinattr_rows", return_value=rows):
        assert dd.resolve_defaultinattr_value("BM1", "multi_vn", 1) is None


def _opts(*values):
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _multi(flag, filled, rows, opts):
    with patch.object(conf, "get_settings", _cfg(cpq_multiselect_default_enabled=flag)), \
            patch.object(conf, "resolve_base_model_vn", return_value="base_vn"), \
            patch.object(dd, "_load_defaultinattr_rows", return_value=rows):
        return conf._resolve_multi_defaults("multi_vn", filled, opts, 1)


def test_multi_defaults_need_the_flag_a_base_model_and_real_options():
    rows = _rows(("BM1", "multi_vn", "a"), ("BM1", "multi_vn", "B"), ("BM1", "multi_vn", "gone"))
    opts = _opts("A", "B", "C")
    got = _multi(True, {"base_vn": "BM1"}, rows, opts)
    assert [o.item_value for o in got] == ["A", "B"]                 # case-insensitive, only real options, option order
    assert _multi(False, {"base_vn": "BM1"}, rows, opts) == []        # flag off
    assert _multi(True, {}, rows, opts) == []                         # base model not resolved yet: no default
    assert _multi(True, {"base_vn": "BM2"}, rows, opts) == []         # another base model has no rows


def test_multi_defaults_without_a_workspace_are_empty():
    with patch.object(conf, "get_settings", _cfg(cpq_multiselect_default_enabled=True)):
        assert conf._resolve_multi_defaults("multi_vn", {}, _opts("A"), None) == []
