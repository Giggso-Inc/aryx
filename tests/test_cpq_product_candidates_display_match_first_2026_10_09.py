"""Regression test for the live stale-candidate-order bug found on ws 1267,
2026-10-09: `resolve_product_cpq_models_from_rows` sorts an exact product
name's real CPQModel candidates alphabetically, with no awareness of which
one the customer actually means.

"APX6500" genuinely resolves to two constraint-proven CPQModels, "APX5500"
and "APX6500/LI" -- alphabetical order puts the unrelated "APX5500" first,
so `derive_base_model_pick.py`/`base_model_narrowing.py` (both of which try
candidates in this exact order and stop at the first with 2+ base models)
ran every derivation/narrowing step against APX5500's own Whitelist data for
an APX 6500 quote. Confirmed live via Basemodeltoconfig: APX6500/LI's own
displayModel IS "APX6500" (an exact match); APX5500's is "APX5500" (no
relation at all).

Fix: `cpq_product_candidates_display_match_first_enabled` moves whichever
candidate(s) Basemodeltoconfig's displayModel confirms as a match for the
product name to the front, reusing `resolve_cpq_model_from_display_name`
(the same mechanism already trusted for free-text hint resolution) rather
than inventing a new matching rule.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.cpq.data_table.data_table_product import resolve_product_cpq_models_from_rows

_PRODUCT_TO_MODELS_KEY = ("_product_to_cpq_models", 1267, "")
_BASEMODEL_TO_CONFIG_KEY = (1267, "", "basemodel_to_config")

_PRODUCT_TO_MODELS = {"APX6500": {"APX5500", "APX6500/LI"}}
_BASEMODEL_TO_CONFIG_ROWS = [
    {"cpqModel": "APX5500", "displayModel": "APX5500"},
    {"cpqModel": "APX6500/LI", "displayModel": "APX6500"},
]


def _cfg(enabled: bool):
    m = MagicMock()
    m.return_value.cpq_product_candidates_display_match_first_enabled = enabled
    return m


def _seeded_cache() -> dict:
    return {
        _PRODUCT_TO_MODELS_KEY: dict(_PRODUCT_TO_MODELS),
        _BASEMODEL_TO_CONFIG_KEY: list(_BASEMODEL_TO_CONFIG_ROWS),
    }


def test_flag_off_keeps_plain_alphabetical_order():
    cache = _seeded_cache()
    with patch("aryx.config.get_settings", _cfg(False)):
        result = resolve_product_cpq_models_from_rows("APX6500", workspace_id=1267, cache=cache)
    assert result == ("APX5500", "APX6500/LI"), "flag off: byte-identical to the original alphabetical sort"


def test_flag_on_moves_the_display_matched_candidate_first():
    cache = _seeded_cache()
    with patch("aryx.config.get_settings", _cfg(True)):
        result = resolve_product_cpq_models_from_rows("APX6500", workspace_id=1267, cache=cache)
    assert result == ("APX6500/LI", "APX5500"), (
        "the candidate whose own displayModel matches the product name must come first, "
        "not the alphabetically-first unrelated sibling"
    )


def test_flag_on_unchanged_when_no_display_name_matches():
    """Control: if nothing in Basemodeltoconfig matches the product name at all, the
    order must stay exactly as it was -- never invent a preference from nothing."""
    cache = {
        _PRODUCT_TO_MODELS_KEY: {"APX6500": {"APX5500", "APX6500/LI"}},
        _BASEMODEL_TO_CONFIG_KEY: [
            {"cpqModel": "APX5500", "displayModel": "SOMETHING ELSE ENTIRELY"},
            {"cpqModel": "APX6500/LI", "displayModel": "SOMETHING ELSE TOO"},
        ],
    }
    with patch("aryx.config.get_settings", _cfg(True)):
        result = resolve_product_cpq_models_from_rows("APX6500", workspace_id=1267, cache=cache)
    assert result == ("APX5500", "APX6500/LI")


def test_flag_on_unchanged_for_a_single_candidate():
    """Control: a product with only one real candidate has nothing to reorder --
    the display-name lookup must not even run (no Basemodeltoconfig cache entry needed)."""
    cache = {_PRODUCT_TO_MODELS_KEY: {"APX6500": {"APX6500/LI"}}}
    with patch("aryx.config.get_settings", _cfg(True)):
        result = resolve_product_cpq_models_from_rows("APX6500", workspace_id=1267, cache=cache)
    assert result == ("APX6500/LI",)


def test_flag_on_two_matched_candidates_keep_their_relative_order():
    """Review of #506 (2026-10-09): none of the original 4 tests covered 2+
    matched candidates. "APX1500" resolves to three candidates; two
    (alphabetically "APX1500ENH" then "APX1500X") both have a displayModel
    matching the product name and must stay in that same relative order in
    front, with the non-matching one pushed behind -- never re-sorted
    independently of each other."""
    cache = {
        _PRODUCT_TO_MODELS_KEY: {"APX1500": {"APX1500ENH", "APX1500X", "APX9999"}},
        (1267, "", "basemodel_to_config"): [
            {"cpqModel": "APX1500ENH", "displayModel": "APX1500"},
            {"cpqModel": "APX1500X", "displayModel": "APX1500"},
            {"cpqModel": "APX9999", "displayModel": "APX9999"},
        ],
    }
    with patch("aryx.config.get_settings", _cfg(True)):
        result = resolve_product_cpq_models_from_rows("APX1500", workspace_id=1267, cache=cache)
    assert result == ("APX1500ENH", "APX1500X", "APX9999")


def test_reordered_result_is_memoized_independent_of_base_model():
    """Review of #506 (2026-10-09): the reorder must be memoized under
    (workspace_id, catalog_prefix, product_name) so a caller invoking this
    with the per-turn cache pays the Basemodeltoconfig scan at most once,
    regardless of how many times (or with what unrelated arguments) it's
    called again for the same product in the same turn."""
    cache = _seeded_cache()
    with patch("aryx.config.get_settings", _cfg(True)):
        first = resolve_product_cpq_models_from_rows("APX6500", workspace_id=1267, cache=cache)
        reorder_key = ("_product_cpq_models_display_matched", 1267, "", "APX6500")
        assert reorder_key in cache, "the reordered result must be cached under this exact key"
        # Poison the Basemodeltoconfig cache entry: if the memo is skipped on the next
        # call, it would scan this (wrong) data and silently produce a different answer.
        cache[_BASEMODEL_TO_CONFIG_KEY] = []
        second = resolve_product_cpq_models_from_rows("APX6500", workspace_id=1267, cache=cache)
    assert first == second == ("APX6500/LI", "APX5500")
