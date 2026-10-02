"""_display_kind's cpq_ingestion_csv_direct branch -- a directly-landed CSV
(cpq_ingestion/csv_land.py, kind=SOURCE_SYSTEM="cpq_ingestion_csv_direct")
is now registered as a datasource so it shows on the Data > Sources page;
this is the label that page renders for it.
"""
from __future__ import annotations

from aryx.source.source_catalog_meta import _display_kind


def test_cpq_csv_direct_kind_renders_as_landed_csv_direct():
    assert _display_kind("cpq_ingestion_csv_direct", "recommendedItems.csv") == "Landed CSV (Direct)"


def test_cpq_csv_direct_kind_wins_over_the_generic_csv_suffix_branch():
    """The registered datasource's `name` ends in ".csv" just like a normal
    CSV upload's does -- without checking `system` first, it would fall
    into the generic ".csv" suffix branch and be mislabeled "Structured
    CSV", losing the distinction that these rows never went through
    resolve/relate/graph projection."""
    assert _display_kind("cpq_ingestion_csv_direct", "catalog.csv") != "Structured CSV"


def test_other_kinds_unaffected():
    assert _display_kind("csv", "catalog.csv") == "Structured CSV"
    assert _display_kind("document", "") == "Document"
    assert _display_kind("rest", "") == "REST API"
    assert _display_kind("cpq_layout", "x.txt") == "CPQ Layout File"
    assert _display_kind("some_other_kind", "") == "Some Other Kind"
