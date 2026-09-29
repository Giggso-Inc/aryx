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


def test_raw_graph_written_to_live_falkordb_and_matches_projection():
    from aryx.cpq_ingestion.raw_graph.store import get_raw_graph_store, write_raw_graph
    from aryx.cpq_ingestion.raw_graph.xml_projector import project_xml_to_raw_graph

    graph_url = os.environ.get("ARYX_GRAPH_URL", "redis://localhost:6379")
    workspace_id = 999_001  # dedicated, disposable test workspace id

    projection = project_xml_to_raw_graph(WRAPPED_XML)
    result = write_raw_graph(projection, workspace_id=workspace_id, dsn="unused", graph_url=graph_url)
    assert result.nodes_written == len(projection.nodes)
    assert result.edges_written == len(projection.edges)

    store = get_raw_graph_store(workspace_id, dsn="unused", graph_url=graph_url)
    live_nodes = store.run_read_only("MATCH (n) RETURN count(n)")
    live_edges = store.run_read_only("MATCH ()-[r]->() RETURN count(r)")
    assert live_nodes[0][0] == len(projection.nodes)
    assert live_edges[0][0] == len(projection.edges)

    store.clear()  # leave no trace in the shared local FalkorDB instance
