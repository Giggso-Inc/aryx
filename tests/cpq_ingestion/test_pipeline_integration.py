"""Live integration test — real FalkorDB, no mocks.

Skipped by default (this repo's default test run should not depend on a
running Docker stack). Opt in with:

    ARYX_RUN_LOCAL_INTEGRATION_TESTS=1 ARYX_GRAPH_URL=redis://localhost:6379 \\
        pytest tests/cpq_ingestion/test_pipeline_integration.py -v

This exercises the exact path wired into file_ingest_run.py end to end
against a real graph store, reproducing the manually-scripted local
verification (see cpq_ingestion/README.md) as a repeatable test.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ARYX_RUN_LOCAL_INTEGRATION_TESTS") != "1",
    reason="opt-in: set ARYX_RUN_LOCAL_INTEGRATION_TESTS=1 with a live FalkorDB reachable",
)

WRAPPED_XML = b"""<Accounts>
  <Account Id="001AC">
    <Name>Acme Robotics</Name>
    <Industry>Manufacturing</Industry>
    <Contacts>
      <Contact Id="003CT">
        <FirstName>Jane</FirstName>
        <LastName>Doe</LastName>
        <Email>jane.doe@acme.com</Email>
      </Contact>
    </Contacts>
  </Account>
</Accounts>
"""

OTHER_XML = b"""<PriceBook Id="PB-1">
  <Entry Sku="WIDGET-A">
    <Price>25.50</Price>
  </Entry>
</PriceBook>
"""


def test_raw_graph_written_to_live_falkordb_and_matches_projection():
    from aryx.cpq_ingestion.raw_graph.store import get_raw_graph_store, write_raw_graph
    from aryx.cpq_ingestion.raw_graph.xml_projector import project_xml_to_raw_graph

    graph_url = os.environ.get("ARYX_GRAPH_URL", "redis://localhost:6379")
    workspace_id = 999_001  # dedicated, disposable test workspace id
    source_key = "accounts_export"

    projection = project_xml_to_raw_graph(WRAPPED_XML)
    result = write_raw_graph(
        projection, workspace_id=workspace_id, source_key=source_key, dsn="unused", graph_url=graph_url,
    )
    assert result.nodes_written == len(projection.nodes)
    assert result.edges_written == len(projection.edges)

    store = get_raw_graph_store(workspace_id, source_key, dsn="unused", graph_url=graph_url)
    live_nodes = store.run_read_only("MATCH (n) RETURN count(n)")
    live_edges = store.run_read_only("MATCH ()-[r]->() RETURN count(r)")
    assert live_nodes[0][0] == len(projection.nodes)
    assert live_edges[0][0] == len(projection.edges)

    store.clear()  # leave no trace in the shared local FalkorDB instance


def test_two_files_in_same_workspace_both_survive_on_live_falkordb():
    """Live regression test for Raven review M1: writing a second XML file
    to the same workspace must not clear the first file's raw graph."""
    from aryx.cpq_ingestion.raw_graph.store import get_raw_graph_store, write_raw_graph
    from aryx.cpq_ingestion.raw_graph.xml_projector import project_xml_to_raw_graph

    graph_url = os.environ.get("ARYX_GRAPH_URL", "redis://localhost:6379")
    workspace_id = 999_002  # dedicated, disposable test workspace id, distinct from the test above

    projection_a = project_xml_to_raw_graph(WRAPPED_XML)
    projection_b = project_xml_to_raw_graph(OTHER_XML)

    write_raw_graph(
        projection_a, workspace_id=workspace_id, source_key="accounts_export",
        dsn="unused", graph_url=graph_url,
    )
    write_raw_graph(
        projection_b, workspace_id=workspace_id, source_key="price_book",
        dsn="unused", graph_url=graph_url,
    )

    store_a = get_raw_graph_store(workspace_id, "accounts_export", dsn="unused", graph_url=graph_url)
    store_b = get_raw_graph_store(workspace_id, "price_book", dsn="unused", graph_url=graph_url)

    nodes_a = store_a.run_read_only("MATCH (n) RETURN count(n)")[0][0]
    nodes_b = store_b.run_read_only("MATCH (n) RETURN count(n)")[0][0]

    # Before the M1 fix, writing file B (into the same workspace_id-only
    # scope) would have cleared file A's graph down to 0 nodes.
    assert nodes_a == len(projection_a.nodes)
    assert nodes_b == len(projection_b.nodes)

    store_a.clear()
    store_b.clear()
