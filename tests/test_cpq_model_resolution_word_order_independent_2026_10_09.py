"""Regression test for the live stale-resolution bug found on ws 1267,
2026-10-09: `model_resolution._match_kind` matched a candidate's display
name by concatenating it into one string (spaces/punctuation stripped) and
checking literal substring containment in the similarly concatenated hint --
so the match only succeeded when the hint said the words in the catalog's
own exact order.

Live: Basemodeltoconfig's displayModel for the Enhanced APX 6500 variant is
"Enhanced APX6500/LI" (adjective-first). A customer asking for "APX 6500
Enhanced" (adjective-last, an equally natural phrasing) normalizes to
"...apx6500enhanced...", which "enhancedapx6500li" is never a substring of --
`ENHANCEDAPX6500/LI` was silently excluded from the candidate pool before
`rank_candidates` ever ran, and the plain (non-Enhanced, data-gap-ridden)
`APX6500/LI` resolved instead.

Fix: `cpq_model_resolution_word_order_independent_enabled` tokenizes both the
candidate's display name and the hint into words and requires every word of
the candidate's name to appear somewhere in the hint, in any order --
`rank_candidates`'s own `longest_name_match` step (untouched) still prefers
the more specific (more-worded) name once both candidates can match.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aryx.cpq import model_resolution as mr
from aryx.cpq import model_resolution_catalog as mrc


def _cfg(enabled: bool):
    m = MagicMock()
    m.return_value.cpq_model_resolution_word_order_independent_enabled = enabled
    return m


class FakeRdb:
    def __init__(self, rows: dict[str, list[dict]]):
        self.rows = rows

    def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
        return [(i, r) for i, r in enumerate(self.rows.get(ontology_type, []))]


def _rdb() -> FakeRdb:
    return FakeRdb({
        "XBmCatalog": [
            {"id": "1", "name": "astro", "parent_id": "-1"},
            {"id": "2", "name": "aPX65005500Series", "parent_id": "1"},
        ],
        "Basemodeltoconfig": [
            {"cpqModel": "APX6500/LI", "displayModel": "APX6500", "CPQModelVariableName": "aPX65005500Series", "baseModel": "T1"},
            {"cpqModel": "APX6500/LI", "displayModel": "APX6500", "CPQModelVariableName": "aPX65005500Series", "baseModel": "T2"},
            {"cpqModel": "ENHANCEDAPX6500/LI", "displayModel": "Enhanced APX6500/LI", "CPQModelVariableName": "aPX65005500Series", "baseModel": "T3"},
            {"cpqModel": "ENHANCEDAPX6500/LI", "displayModel": "Enhanced APX6500/LI", "CPQModelVariableName": "aPX65005500Series", "baseModel": "T4"},
        ],
        "Flagsforflashport": [],
        "XBmConfigRule": [],
    })


@pytest.fixture(autouse=True)
def _clean():
    mrc._cache.clear()
    mrc._empty.clear()
    mr.bind_turn(None)
    yield
    mrc._cache.clear()
    mrc._empty.clear()
    mr.bind_turn(None)


def _resolve(text: str) -> mr.ModelResolution:
    return mr.resolve_model(text, 1, "X", _rdb())


def test_flag_off_keeps_word_order_sensitive_match():
    with patch("aryx.config.get_settings", _cfg(False)):
        res = _resolve("Quote for APX 6500 Enhanced in US")
    assert res.resolved and res.chosen.cpq_model == "APX6500/LI", (
        "flag off: byte-identical to the original word-order-sensitive behavior -- "
        "'Enhanced' trailing the model number still fails to match 'Enhanced APX6500/LI'"
    )


def test_flag_on_resolves_enhanced_variant_regardless_of_word_order():
    with patch("aryx.config.get_settings", _cfg(True)):
        res = _resolve("Quote for APX 6500 Enhanced in US")
    assert res.resolved and res.chosen.cpq_model == "ENHANCEDAPX6500/LI", (
        "flag on: every word of 'Enhanced APX6500/LI' ('enhanced', 'apx6500', 'li') "
        "appears in the hint's tokens regardless of order, and longest_name_match "
        "then prefers it over the shorter plain APX6500/LI"
    )


def test_flag_on_still_matches_the_catalogs_own_word_order():
    """Control: the fix is a strict superset -- a hint that already matches in the
    catalog's own word order must keep matching exactly as before."""
    with patch("aryx.config.get_settings", _cfg(True)):
        res = _resolve("I'd like an Enhanced APX6500/LI please")
    assert res.resolved and res.chosen.cpq_model == "ENHANCEDAPX6500/LI"


def test_flag_on_digit_bleed_guard_preserved_by_whole_word_tokens():
    """Control: tokenizing into whole words naturally preserves the intent of the
    old `_occurs` digit-boundary guard -- "apx6500" as its own token in the hint
    must not accidentally satisfy a candidate word of "apx65005" or similar,
    since tokens are compared for exact equality, not substring containment."""
    rdb = FakeRdb({
        "XBmCatalog": [{"id": "1", "name": "astro", "parent_id": "-1"}],
        "Basemodeltoconfig": [
            {"cpqModel": "APX65005", "displayModel": "APX65005", "baseModel": "T1"},
            {"cpqModel": "APX65005", "displayModel": "APX65005", "baseModel": "T2"},
        ],
        "Flagsforflashport": [],
        "XBmConfigRule": [],
    })
    with patch("aryx.config.get_settings", _cfg(True)):
        res = mr.resolve_model("quote an APX6500 please", 1, "X", rdb)
    assert not res.resolved
