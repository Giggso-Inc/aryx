"""_display_kind's cpq_layout branch -- CPQ_LAYOUT_FILE_STORAGE_MIGRATION_
PLAN_2026-09-30.md follow-up: an uploaded layout file is now registered as
a datasource (kind="cpq_layout") so it shows on the Data > Sources page;
this is the label that page renders for it.
"""
from __future__ import annotations

from aryx.source.source_catalog_meta import _display_kind


def test_cpq_layout_kind_renders_as_cpq_layout_file():
    assert _display_kind("cpq_layout", "Config Layout APX Next.txt") == "CPQ Layout File"


def test_cpq_layout_kind_takes_priority_over_generic_title_case_fallback():
    """Without the explicit branch, "cpq_layout" would fall through to the
    generic system.replace("_", " ").title() fallback ("Cpq Layout") --
    the explicit branch must win."""
    assert _display_kind("cpq_layout", "") != "Cpq Layout"


def test_other_kinds_unaffected():
    assert _display_kind("csv", "") == "Structured CSV"
    assert _display_kind("document", "") == "Document"
    assert _display_kind("rest", "") == "REST API"
    assert _display_kind("some_other_kind", "") == "Some Other Kind"
