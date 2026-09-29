"""Raw-graph storage-scope naming — kept distinct from the curated graph's
scope, and distinct per source file within one workspace (Raven review M1)."""
from __future__ import annotations

from aryx.cpq_ingestion.naming import raw_workspace_id, raw_ws_graph
from aryx.naming import ws_graph


def test_raw_ws_graph_name_format():
    assert raw_ws_graph(50, "catalog") == "aryx_raw_ws_50_catalog"


def test_raw_ws_graph_never_collides_with_curated_ws_graph():
    for workspace_id in (0, 1, 50, 999_999):
        assert raw_ws_graph(workspace_id, "catalog") != ws_graph(workspace_id)


def test_raw_ws_graph_differs_per_source_file_in_same_workspace():
    """Regression guard for M1: two XML files in one job must not collide."""
    first = raw_ws_graph(50, "aSTRO25_ConfigData")
    second = raw_ws_graph(50, "aSTRO25_PriceBook")
    assert first != second


def test_raw_ws_graph_sanitizes_unsafe_characters_in_source_key():
    name = raw_ws_graph(50, "my file (v2).xml")
    assert name.startswith("aryx_raw_ws_50_")
    assert " " not in name and "(" not in name and "." not in name


def test_raw_ws_graph_never_empty_for_empty_source_key():
    assert raw_ws_graph(50, "") == "aryx_raw_ws_50_file"


def test_raw_workspace_id_is_offset_and_workspace_scoped():
    offset = 1_000_000_000
    value = raw_workspace_id(50, offset, "catalog")
    assert value > offset
    assert value != 50


def test_raw_workspace_id_never_collides_across_workspaces_for_any_source_key():
    """The multiplicative workspace stride must keep different workspaces'
    derived ranges from ever overlapping, regardless of source_key."""
    offset = 1_000_000_000
    for source_key in ("a", "b", "aSTRO25_ConfigData", ""):
        assert raw_workspace_id(50, offset, source_key) != raw_workspace_id(51, offset, source_key)


def test_raw_workspace_id_differs_per_source_file_in_same_workspace():
    """Regression guard for M1 on the Oracle backend: two XML files in one
    job must resolve to different workspace_ids (barring a hash collision,
    which the docstring documents as a bounded, acceptable residual risk)."""
    offset = 1_000_000_000
    first = raw_workspace_id(50, offset, "aSTRO25_ConfigData")
    second = raw_workspace_id(50, offset, "aSTRO25_PriceBook")
    assert first != second


def test_raw_workspace_id_is_deterministic():
    offset = 1_000_000_000
    assert raw_workspace_id(50, offset, "catalog") == raw_workspace_id(50, offset, "catalog")
