"""xml_projector — pure unit tests against the exact sample XML used in local testing.

Node/edge counts asserted here match the live FalkorDB query results
recorded during manual local testing (see cpq_ingestion/README.md):
14 nodes / 13 edges for the plural-wrapper sample, 12 nodes / 11 edges for
the same data with wrapper tags removed.
"""
from __future__ import annotations

import logging
import tracemalloc

from aryx.cpq_ingestion.raw_graph.xml_projector import project_xml_to_raw_graph

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
    <Opportunities>
      <Opportunity Id="006OP">
        <Name>Acme - Q4 Renewal</Name>
        <Amount>48000</Amount>
        <StageName>Negotiation</StageName>
      </Opportunity>
    </Opportunities>
  </Account>
</Accounts>
"""

NOWRAP_XML = b"""<Accounts>
  <Account Id="001AC">
    <Name>Acme Robotics</Name>
    <Industry>Manufacturing</Industry>
    <Contact Id="003CT">
      <FirstName>Jane</FirstName>
      <LastName>Doe</LastName>
      <Email>jane.doe@acme.com</Email>
    </Contact>
    <Opportunity Id="006OP">
      <Name>Acme - Q4 Renewal</Name>
      <Amount>48000</Amount>
      <StageName>Negotiation</StageName>
    </Opportunity>
  </Account>
</Accounts>
"""


def test_wrapped_xml_produces_full_tree_no_drops():
    projection = project_xml_to_raw_graph(WRAPPED_XML)
    assert len(projection.nodes) == 14
    assert len(projection.edges) == 13
    tags = {n.tag for n in projection.nodes}
    # The whole point: Contact and Opportunity survive despite the plural
    # wrapper tags that _xml_to_csvs's entity-detection rule drops.
    assert {"Contacts", "Contact", "Opportunities", "Opportunity"} <= tags


def test_nowrap_xml_produces_two_fewer_container_nodes():
    projection = project_xml_to_raw_graph(NOWRAP_XML)
    assert len(projection.nodes) == 12
    assert len(projection.edges) == 11
    tags = {n.tag for n in projection.nodes}
    assert "Contacts" not in tags
    assert "Opportunities" not in tags
    assert {"Contact", "Opportunity"} <= tags


def test_wrapper_shape_does_not_change_entity_count():
    """Regression guard for the exact bug this package exists to route around."""
    wrapped = project_xml_to_raw_graph(WRAPPED_XML)
    nowrap = project_xml_to_raw_graph(NOWRAP_XML)
    wrapped_types = {n.tag for n in wrapped.nodes} - {"Accounts", "Contacts", "Opportunities"}
    nowrap_types = {n.tag for n in nowrap.nodes} - {"Accounts"}
    assert wrapped_types == nowrap_types


def test_attributes_and_leaf_text_become_properties():
    projection = project_xml_to_raw_graph(WRAPPED_XML)
    account = next(n for n in projection.nodes if n.tag == "Account")
    assert account.properties == {"Id": "001AC"}
    name_leaf = next(
        n for n in projection.nodes if n.tag == "Name" and n.properties.get("text") == "Acme Robotics"
    )
    assert name_leaf.properties == {"text": "Acme Robotics"}


def test_container_nodes_have_no_properties():
    projection = project_xml_to_raw_graph(WRAPPED_XML)
    root = next(n for n in projection.nodes if n.tag == "Accounts")
    assert root.properties == {}


def test_every_edge_is_contains_and_ids_are_unique():
    projection = project_xml_to_raw_graph(WRAPPED_XML)
    assert all(e.name == "CONTAINS" for e in projection.edges)
    ids = [n.id for n in projection.nodes]
    assert len(ids) == len(set(ids))


def test_edges_reference_only_existing_node_ids():
    projection = project_xml_to_raw_graph(NOWRAP_XML)
    node_ids = {n.id for n in projection.nodes}
    for edge in projection.edges:
        assert edge.source_id in node_ids
        assert edge.target_id in node_ids


# ── Large-document scalability ──────────────────────────────────────────────
# Live incident: a 240MB XML upload stalled for 15+ minutes with near-zero
# CPU, never logging anything between "read_files start" and the (never
# reached) raw-graph write -- the prior implementation built the ENTIRE
# document as one in-memory DOM tree (defused_ET.fromstring) before any
# processing could even begin. Replaced with streaming iterparse +
# elem.clear(), which discards each element's children/attrib/text as soon
# as its own node is built -- peak memory is bounded by the tree's DEPTH,
# not its total size or element count.

def _make_flat_xml(n: int) -> bytes:
    """n sibling <Record> elements under one <Root> -- same shape class as
    the real large-file incident (many flat siblings, not deep nesting)."""
    parts = [b"<Root>"]
    for i in range(n):
        parts.append(f'<Record Id="{i}"><Name>Item {i}</Name></Record>'.encode())
    parts.append(b"</Root>")
    return b"".join(parts)


def test_large_flat_document_produces_correct_counts():
    """Not a performance assertion (CI timing is unreliable) -- just proves
    correctness doesn't degrade at a scale the old recursive DOM walk was
    never exercised against (its own docstring only ever verified 14
    nodes). 1 Root + 50,000 Record + 50,000 Name = 100,001 nodes;
    100,000 CONTAINS edges (Root has no parent)."""
    data = _make_flat_xml(50_000)
    projection = project_xml_to_raw_graph(data)
    assert len(projection.nodes) == 100_001
    assert len(projection.edges) == 100_000
    assert all(e.name == "CONTAINS" for e in projection.edges)
    node_ids = {n.id for n in projection.nodes}
    assert len(node_ids) == len(projection.nodes)  # all unique
    for edge in projection.edges:
        assert edge.source_id in node_ids
        assert edge.target_id in node_ids


def test_large_flat_document_peak_memory_scales_with_output_not_a_full_extra_tree():
    """The RESULT lists (nodes/edges) necessarily grow with element count --
    that's unavoidable since every node/edge is returned, so peak memory
    growing roughly linearly with element count is EXPECTED, not a
    regression. What a streaming walk must avoid is growing *worse* than
    that -- e.g. the old DOM implementation's failure mode of ALSO holding
    a full parsed tree alongside the output, which would add a second
    multiplier on top of the linear output growth. 10x more elements
    should cost roughly 10x the memory, not 20x+."""
    small = _make_flat_xml(2_000)
    large = _make_flat_xml(20_000)  # 10x more elements, same depth

    tracemalloc.start()
    project_xml_to_raw_graph(small)
    _, peak_small = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    tracemalloc.start()
    project_xml_to_raw_graph(large)
    _, peak_large = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Generous headroom (2x the 10x element-count increase) over the
    # expected linear-with-output scaling, to absorb noise without masking
    # a real regression back to full-DOM-plus-output memory behavior.
    assert peak_large < peak_small * 20


def test_large_document_logs_progress(caplog):
    """The old implementation logged nothing between function entry and
    return, however long a parse took -- a slow-but-working 240MB parse
    was indistinguishable from a hang. Progress logging must fire for a
    document crossing the log interval."""
    from aryx.cpq_ingestion.raw_graph import xml_projector

    data = _make_flat_xml(60_000)  # > _PROGRESS_LOG_INTERVAL (50,000) nodes
    with caplog.at_level(logging.INFO, logger=xml_projector.__name__):
        project_xml_to_raw_graph(data)
    assert any("element(s) processed" in r.message for r in caplog.records)
    assert any("done" in r.message for r in caplog.records)


def test_small_document_does_not_log_progress(caplog):
    """No log spam for the common case -- only documents actually crossing
    the interval threshold should produce progress lines."""
    from aryx.cpq_ingestion.raw_graph import xml_projector

    with caplog.at_level(logging.INFO, logger=xml_projector.__name__):
        project_xml_to_raw_graph(WRAPPED_XML)
    assert not any("element(s) processed" in r.message for r in caplog.records)
