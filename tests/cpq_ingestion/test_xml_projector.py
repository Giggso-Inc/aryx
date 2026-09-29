"""xml_projector — pure unit tests against the exact sample XML used in local testing.

Node/edge counts asserted here match the live FalkorDB query results
recorded during manual local testing (see cpq_ingestion/README.md):
14 nodes / 13 edges for the plural-wrapper sample, 12 nodes / 11 edges for
the same data with wrapper tags removed.
"""
from __future__ import annotations

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
