"""ws 1267 (2026-10-07): APX 1500 / 1500 Enhanced / 4500 / 4500 Enhanced each have a hierarchy row with a BLANK Product
and their own displayCPQModel, so no Product matched and the product fell to the static APX NEXT fallback (nothing
scoped, ~45 guessed fills a turn). The row's display is the product's name; it is matched exactly, only on proof."""
from __future__ import annotations

import pytest

from aryx.cpq.data_table import data_table_product as dtp
from aryx.cpq.data_table_bridge.candidates import _cpq_model_candidates

HIERARCHY = [
    {"productFamily": "aSTRO25", "cpqModelName": "APX1500", "displayCPQModel": "APX 1500"},
    {"productFamily": "aSTRO25", "cpqModelName": "APX1500ENH", "displayCPQModel": "APX 1500 Enhanced"},
    {"productFamily": "aSTRO25", "cpqModelName": "APX4500", "displayCPQModel": "APX 4500"},
    {"productFamily": "aSTRO25", "cpqModelName": "APX4500ENH", "displayCPQModel": "APX 4500 Enhanced"},
    {"productFamily": "aSTRO25", "cpqModelName": "APX900", "displayCPQModel": "APX 900"},
    {"productFamily": "aSTRO25", "cpqModelName": "APXFLASHPORTSERIES", "Product": "APX900FLASHPORT",
     "displayCPQModel": "APX 900 FLASHport"},
]
ALL = ["APX1500", "APX1500ENH", "APX4500", "APX4500ENH", "APX900"]


@pytest.fixture(autouse=True)
def _fresh():
    dtp._clear_sequence_model_codes_cache()
    yield
    dtp._clear_sequence_model_codes_cache()


@pytest.fixture
def tables(monkeypatch):
    def install(sequence_models=ALL):
        seq = [{"CPQModel": m, "AttrName": "x"} for m in sequence_models]
        monkeypatch.setattr(dtp, "_load_all_tables", lambda *a, **k: ([], seq, list(HIERARCHY), [], []))
    return install


@pytest.mark.parametrize("name,expected", [
    ("APX 1500 Enhanced", ("APX1500ENH",)),
    ("APX 1500", ("APX1500",)),
    ("apx  4500   ENHANCED", ("APX4500ENH",)),                       # case and whitespace normalised
    ("APX 4500", ("APX4500",)),
])
def test_the_model_whose_row_is_displayed_as_the_product_is_found(tables, name, expected):
    tables()
    assert dtp.resolve_models_by_hierarchy_display(name, 1267) == expected


def test_candidates_put_the_real_model_first_instead_of_the_static_fallback(tables):
    tables()
    assert _cpq_model_candidates("APX 1500 Enhanced", 1267)[:2] == ("APX1500ENH", "APX1500ENH_BOM")
    assert _cpq_model_candidates("APX 4500 Enhanced", 1267)[:2] == ("APX4500ENH", "APX4500ENH_BOM")


def test_a_model_without_sequence_rows_is_not_used(tables):
    tables(["APX900"])
    assert dtp.resolve_models_by_hierarchy_display("APX 1500 Enhanced", 1267) == ()
    assert _cpq_model_candidates("APX 1500 Enhanced", 1267)[:2] == ("APXNEXT", "APXNEXT_BOM")


@pytest.mark.parametrize("name", ["", "   ", "APX", "aSTRO25", "APX 1500 Enhanced Plus", "APX 15"])
def test_empty_one_word_or_inexact_names_match_nothing(tables, name):
    tables()
    assert dtp.resolve_models_by_hierarchy_display(name, 1267) == ()


def test_a_product_that_the_hierarchy_names_by_product_is_untouched(tables):
    """APX900FLASHPORT has its own Product row: the Product-keyed path decides, as before."""
    tables()
    assert _cpq_model_candidates("APX900FLASHPORT", 1267)[:2] == ("APX900", "APX900_BOM")
