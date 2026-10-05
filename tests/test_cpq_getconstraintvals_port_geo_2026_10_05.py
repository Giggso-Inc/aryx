"""Plan F1 + F5 (docs/oci-oracle/CONFIG_DATA_REQUIRED_FIELDS_INGEST_AND_FIX_PLAN_
2026-10-05.md): the util.getConstraintVals port and the country/region + RTTE
readers. Both are flag-gated and must leave behaviour unchanged when off.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aryx.cpq.bml import bml_util_substitution as sub
from aryx.cpq.data_table import data_table_geo as geo
from aryx.cpq.data_table import data_table_getconstraintvals as gcv
from aryx.cpq.data_table.data_table_shapes import (
    _detect_shape, _is_country_region_shaped, _is_rtte_ta_shaped,
)
from aryx.cpq.engine import _clear_substitute_util_get_constraint_vals_cache
from aryx.cpq.governance_and_sibling_exclusivity import region as region_mod
from aryx.cpq.state import ConfigAttr, MenuOption


def _cfg(**kw):
    m = MagicMock()
    for k, v in kw.items():
        setattr(m.return_value, k, v)
    return m


# ── F5: shapes and readers ────────────────────────────────────────────────

def test_geo_shapes_are_detected_and_disjoint_from_the_pooled_shapes():
    cr = {"countryCode", "countryDesc", "region", "emsParent"}
    rt = {"countryCode", "countryDesc", "RTTE", "nonRTTE", "TA"}
    assert _is_country_region_shaped(cr) and not _is_rtte_ta_shaped(cr)
    assert _is_rtte_ta_shaped(rt) and not _is_country_region_shaped(rt)
    assert _detect_shape(cr) is None and _detect_shape(rt) is None


def test_resolve_country_region_reads_the_table_case_insensitively():
    rows = [{"countryCode": "GB", "region": "EA"}, {"countryCode": "US", "region": "NA"}]
    with patch.object(geo, "_cached_shape_scan", return_value=rows):
        assert geo.resolve_country_region("us", 1) == "NA"
        assert geo.resolve_country_region("GB", 1) == "EA"
        assert geo.resolve_country_region("ZZ", 1) is None
        assert geo.resolve_country_region("", 1) is None


def test_resolve_rtte_flag_picks_the_one_flag_set():
    rows = [
        {"countryCode": "DE", "RTTE": "Yes", "nonRTTE": "", "TA": ""},
        {"countryCode": "AE", "RTTE": "", "nonRTTE": "Yes", "TA": ""},
        {"countryCode": "AL", "RTTE": "", "nonRTTE": "", "TA": "Yes"},
        {"countryCode": "XX", "RTTE": "", "nonRTTE": "", "TA": ""},
    ]
    with patch.object(geo, "_cached_shape_scan", return_value=rows):
        assert [geo.resolve_rtte_flag(c, 1) for c in ("DE", "AE", "AL", "XX", "ZZ")] == [
            "RTTE", "NON RTTE", "TA", None, None]


def _region_attr(*codes):
    return ConfigAttr(
        entity_id=1, variable_name="modelSelectionRegion_astro", display_label="Region", required=False,
        default_value="", options=[MenuOption(item_value=c, display_name=c, order=1) for c in codes],
    )


def test_derive_region_table_is_flag_gated_and_falls_back_to_the_constant():
    attr = _region_attr("NA", "EA", "LA")
    with patch.object(region_mod, "resolve_country_region", return_value="LA") as table:
        with patch.object(region_mod, "get_settings", _cfg(cpq_country_region_table_enabled=False)):
            assert region_mod.derive_region("canada", attr, 7)[0] == "NA"       # constant, table untouched
            table.assert_not_called()
        with patch.object(region_mod, "get_settings", _cfg(cpq_country_region_table_enabled=True)):
            assert region_mod.derive_region("canada", attr, 7)[0] == "LA"       # table wins
            assert region_mod.derive_region("canada", attr)[0] == "NA"          # no workspace: constant
    with patch.object(region_mod, "resolve_country_region", return_value=None), \
            patch.object(region_mod, "get_settings", _cfg(cpq_country_region_table_enabled=True)):
        assert region_mod.derive_region("canada", attr, 7)[0] == "NA"           # table has no row: constant


# ── F1: the port ──────────────────────────────────────────────────────────

def _seq(model, base, *attrs):
    return [{"CPQModel": model, "BaseModel": base, "AttrName": a, "Seq": str(n), "optionOrReqFlag": f}
            for a, n, f in attrs]


def _wl(model, base, *cols):
    row = {"CPQModel": model, "BaseModel": base}
    for i, (a, v) in enumerate(cols, 1):
        row[f"attr{i}"], row[f"val{i}"] = a, v
    return row


def _run(constraint, sequence, target, filled, model="M", base="B"):
    with patch.object(gcv, "_load_all_tables", return_value=(constraint, sequence, [], [], [])):
        return gcv.get_constraint_vals(model, base, target, filled, 1)


SEQ = _seq("M", "B", ("early", 1, "O"), ("target", 5, "O"), ("late", 9, "O"))


def test_only_earlier_attributes_filter_a_row():
    rows = [_wl("M", "B", ("target", "X"), ("early", "e1"), ("late", "l1"))]
    got = _run(rows, SEQ, "target", {"early": "e1"})            # `late` is after the target: ignored
    assert got["values"] == ["X"]
    assert _run(rows, SEQ, "target", {"early": "other"})["values"] == []


def test_filter_attribute_with_no_value_rejects_the_row():
    rows = [_wl("M", "B", ("target", "X"), ("early", "e1"))]
    assert _run(rows, SEQ, "target", {})["values"] == []


def test_attribute_missing_from_the_sequence_counts_as_zero_and_filters():
    rows = [_wl("M", "B", ("target", "X"), ("ghost", "g1"))]
    assert _run(rows, SEQ, "target", {"ghost": "g1"})["values"] == ["X"]
    assert _run(rows, SEQ, "target", {})["values"] == []


def test_target_can_sit_in_any_column():
    rows = [_wl("M", "B", ("early", "e1"), ("target", "Y"))]
    assert _run(rows, SEQ, "target", {"early": "e1"})["values"] == ["Y"]


def test_multi_select_filter_values_split_on_tilde_and_comma():
    rows = [_wl("M", "B", ("target", "X"), ("early", "e2"))]
    assert _run(rows, SEQ, "target", {"early": "e1~e2~e3"})["values"] == ["X"]
    assert _run(rows, SEQ, "target", {"early": "e1,e2"})["values"] == ["X"]
    assert _run(rows, SEQ, "target", {"early": "e1~e3"})["values"] == []


def test_all_base_model_rows_apply_and_values_are_deduplicated():
    rows = [_wl("M", "ALL", ("target", "X")), _wl("M", "B", ("target", "X")), _wl("M", "OTHER", ("target", "Z"))]
    assert _run(rows, SEQ, "target", {})["values"] == ["X"]


def test_r_flag_or_a_check_value_removes_the_blank_option():
    rows = [_wl("M", "B", ("target", "X"))]
    assert _run(rows, SEQ, "target", {})["blank_allowed"] is True
    seq_r = _seq("M", "B", ("target", 5, "R"))
    got = _run(rows, seq_r, "target", {})
    assert got["required"] and not got["blank_allowed"]
    chk = [_wl("M", "B", ("target", "NO CHARGER"))]
    assert _run(chk, SEQ, "target", {})["required"] is True


def test_unknown_cases_return_none_and_not_in_sequence_returns_only_a_blank():
    rows = [_wl("M", "B", ("target", "X"))]
    assert _run(rows, [], "target", {}) is None                                   # no sequence rows: unknown
    assert _run([_wl("M", "B", ("other", "Q"))], SEQ, "target", {}) is None      # no row names the target
    assert _run(rows, _seq("M", "B", ("early", 1, "O")), "target", {}) == {
        "values": [], "blank_allowed": True, "required": False}


# ── F1: substitution wiring ───────────────────────────────────────────────

_SCRIPT = (
    'params.put(inputParam, "Attribute Variable Name", "target");\n'
    "returnVal = util.getConstraintVals(dictVar, listVar);"
)
_FILLED = {"modelSelectionbaseModel_astro": "B", "productSelectionProduct_all": "P"}


def _subst(flag):
    _clear_substitute_util_get_constraint_vals_cache()
    with patch.object(sub, "get_settings", _cfg(cpq_getconstraintvals_port_enabled=flag)), \
            patch("aryx.cpq.engine._cpq_model_candidates", return_value=("M",)), \
            patch("aryx.cpq.engine.dt_resolve_whitelist_values", return_value=["OLD"]) as old, \
            patch.object(sub, "get_constraint_vals", return_value={"values": ["NEW"]}) as new:
        out = sub._substitute_util_get_constraint_vals(_SCRIPT, _FILLED, 5, "", None)
    _clear_substitute_util_get_constraint_vals_cache()
    return out, old.call_count, new.call_count


def test_substitution_uses_the_old_resolver_when_off_and_the_port_when_on():
    out, old_calls, new_calls = _subst(False)
    assert '"OLD"' in out and (old_calls, new_calls) == (1, 0)
    out, old_calls, new_calls = _subst(True)
    assert '"NEW"' in out and (old_calls, new_calls) == (0, 1)
