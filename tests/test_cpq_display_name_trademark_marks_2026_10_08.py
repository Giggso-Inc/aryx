"""A trademark mark in a catalog display name must not hide the real model (ws 1267, "i want to quote APX N50 for US").

Dev's Basemodeltoconfig names the real model "APX(TM) N50" and its flashport rows plain "APX N50". The matcher looks for the
display name inside the customer's wording, so only the flashport rows matched: the not-applicable guard resolved
["APXN50FLASHPORT"] alone, found no frequency band in its rows, cleared the band, and the base model could not be narrowed.
With ``cpq_model_scoped_questions_enabled`` the marks are ignored and both models of that name are returned. Off: unchanged."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from aryx.config import get_settings
from aryx.cpq.data_table import data_table_cache, data_table_inference, data_table_loader  # noqa: F401
from aryx.cpq.data_table import data_table_product as product
from aryx.cpq.data_table.data_table_resolver import resolve_cpq_model_from_display_name

TM = "™"


@pytest.fixture
def flags():
    s = get_settings()
    previous = s.cpq_model_scoped_questions_enabled
    data_table_loader._clear_tables_cache()
    yield s
    s.cpq_model_scoped_questions_enabled = previous
    data_table_loader._clear_tables_cache()


def _rows(*pairs):
    return [{"displayModel": d, "cpqModel": c, "baseModel": b} for d, c, b in pairs]


# the real shape of dev's table for N50 and N30
ROWS = _rows((f"APX{TM} N50", "APXN50", "H25UCF9PW6AN"), (f"APX{TM} N50", "APXN50", "H25KDF9PW6AN"),
             ("APX N50", "APXN50FLASHPORT", "T9913A"), ("APX N50", "APXN50FLASHPORT", "T9916A"),
             (f"APX{TM} N30", "APXN30", "H15UCF9PW6AN"), ("APX N30", "APXN30FLASHPORT", "T9912A"))


def _resolve(hint, rows=ROWS):
    with patch.object(data_table_inference, "_load_basemodel_to_config_rows", return_value=rows):
        return resolve_cpq_model_from_display_name(hint, 1267, "Astro25Configdata")


def test_the_display_key_ignores_marks_only_when_asked():
    assert product._display_key(f"APX{TM} N50", True) == "APX N50"
    assert product._display_key(f"APX{TM} N50", False) == f"APX{TM} N50"
    assert product._display_key("  apx   n50 ", True) == "APX N50"            # whitespace collapsed, spacing between words kept
    assert product._display_key("APX® N50©", True) == "APX N50" and product._display_key(None, True) == ""


def test_with_the_flag_both_models_of_the_name_are_returned(flags):
    flags.cpq_model_scoped_questions_enabled = True
    assert _resolve("i want to quote APX N50 for US") == ("APXN50", "APXN50FLASHPORT")
    assert _resolve("i want to quote APX N30 for US") == ("APXN30", "APXN30FLASHPORT")


def test_without_the_flag_only_the_plain_spelled_rows_match_as_before(flags):
    flags.cpq_model_scoped_questions_enabled = False
    assert _resolve("i want to quote APX N50 for US") == ("APXN50FLASHPORT",)


def test_a_customer_who_types_the_mark_matches_too(flags):
    flags.cpq_model_scoped_questions_enabled = True
    assert _resolve(f"quote APX{TM} N50 please") == ("APXN50", "APXN50FLASHPORT")


def test_spacing_inside_a_name_still_matters(flags):
    """A catalog can map "APX3000" and "APX 3000" to different models: only marks are ignored, never spaces."""
    flags.cpq_model_scoped_questions_enabled = True
    rows = _rows(("APX3000", "TXM3000", "T05"), (f"APX{TM} 3000", "APX3000", "H59"))
    assert _resolve("I want APX 3000 for US", rows) == ("APX3000",)
    assert _resolve("I want APX3000 for US", rows) == ("TXM3000",)


def test_the_longest_name_still_wins_for_nested_names(flags):
    flags.cpq_model_scoped_questions_enabled = True
    rows = _rows((f"APX{TM} 3000", "APX3000", "H59"), ("APX 3000 FLASHPORT", "APX3000FLASHPORT", "T79"))
    assert _resolve("I want APX 3000 FLASHPORT for US", rows) == ("APX3000FLASHPORT",)
    assert _resolve("I want APX 3000 for US", rows) == ("APX3000",)


def test_two_unrelated_names_in_one_wording_stay_unresolved(flags):
    flags.cpq_model_scoped_questions_enabled = True
    assert _resolve("compare APX N50 and APX N30") == ()


def test_the_guard_no_longer_clears_an_attribute_the_real_model_lists(flags):
    """The consequence on dev: the guard asks whether ANY resolved model governs the attribute."""
    from aryx.cpq.engine import CpqEngine

    flags.cpq_model_scoped_questions_enabled = True
    governs = {"APXN50": True, "APXN50FLASHPORT": False}                      # the band is listed for the real model only
    with patch("aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
               side_effect=lambda hint, *a, **k: _resolve(hint)), \
            patch("aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model", side_effect=lambda cm, vn, *a, **k: governs[cm]):
        assert CpqEngine._named_attr_confirmed_not_applicable("modelSelectionFrequencyBands_astro", "quote APX N50 for US", 1, "p") is False
        flags.cpq_model_scoped_questions_enabled = False                      # before: flashport alone, band "not applicable"
        assert CpqEngine._named_attr_confirmed_not_applicable("modelSelectionFrequencyBands_astro", "quote APX N50 for US", 1, "p") is True
