"""Raw-graph storage-scope naming — kept distinct from the curated graph's scope."""
from __future__ import annotations

from aryx.cpq_ingestion.naming import raw_workspace_id, raw_ws_graph
from aryx.naming import ws_graph


def test_raw_ws_graph_name_format():
    assert raw_ws_graph(50) == "aryx_raw_ws_50"


def test_raw_ws_graph_never_collides_with_curated_ws_graph():
    for workspace_id in (0, 1, 50, 999_999):
        assert raw_ws_graph(workspace_id) != ws_graph(workspace_id)


def test_raw_workspace_id_is_additive_offset():
    assert raw_workspace_id(50, 1_000_000_000) == 1_000_000_050
    assert raw_workspace_id(0, 1_000_000_000) == 1_000_000_000


def test_raw_workspace_id_differs_from_curated_for_any_positive_offset():
    for workspace_id in (0, 1, 50, 999_999):
        assert raw_workspace_id(workspace_id, 1_000_000_000) != workspace_id


def test_raw_workspace_id_accepts_numeric_strings_like_the_rest_of_the_codebase():
    """workspace_id often arrives as a plain int already, but naming.ws_graph()
    coerces with int() too — mirror that tolerance rather than assuming a type."""
    assert raw_workspace_id("50", 1_000_000_000) == 1_000_000_050
