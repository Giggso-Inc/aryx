"""normalize_value: shared normalization used by both dynamic FK detection and
the exact-match join in fk_edges.link_by_attribute — leading-zero, case, and
whitespace differences must not silently prevent a real relationship from
being recognized or joined."""
from __future__ import annotations

from aryx.pipeline.value_normalize import normalize_value


def test_case_insensitive():
    assert normalize_value("AE") == normalize_value("ae")


def test_whitespace_stripped():
    assert normalize_value("  AE  ") == normalize_value("AE")


def test_leading_zeros_stripped_for_numeric_values():
    assert normalize_value("007") == normalize_value("7")


def test_all_zero_numeric_value_preserved_as_zero():
    assert normalize_value("000") == "0"


def test_alphanumeric_identifier_not_touched():
    # "DS000E1LA" is NOT purely digits — must not be zero-stripped.
    assert normalize_value("DS000E1LA") == "ds000e1la"
    assert normalize_value("DS000E1LA") != normalize_value("DSE1LA")


def test_distinct_values_remain_distinct():
    assert normalize_value("AE") != normalize_value("AK")
