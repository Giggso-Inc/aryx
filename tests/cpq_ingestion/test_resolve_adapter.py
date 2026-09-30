"""RawGraphConnector / group_nodes_by_tag -- the resolve/relate bridge's
first piece: replaying raw graph nodes as RawRecords through the same
Connector seam RecordsConnector already uses for document mentions.

No resolve/relate orchestration is exercised here (that's a later piece,
not built yet) -- these tests only cover the connector's own contract:
grouping by tag, RawRecord shape, and record_id uniqueness across files.
"""
from __future__ import annotations

from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawGraphProjection, RawNode
from aryx.cpq_ingestion.raw_graph.resolve_adapter import (
    SOURCE_SYSTEM,
    RawGraphConnector,
    group_nodes_by_tag,
    parse_record_id,
)
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


def _projection() -> RawGraphProjection:
    return project_xml_to_raw_graph(WRAPPED_XML)


def test_group_nodes_by_tag_buckets_every_node_under_its_tag():
    projection = _projection()

    by_tag = group_nodes_by_tag(projection)

    assert set(by_tag) >= {"Account", "Contact", "Opportunity"}
    assert all(node.tag == tag for tag, nodes in by_tag.items() for node in nodes)
    assert sum(len(nodes) for nodes in by_tag.values()) == len(projection.nodes)


def test_group_nodes_by_tag_groups_repeated_tags_together():
    nodes = [
        RawNode(id=0, tag="LineItem", properties={"Sku": "A"}),
        RawNode(id=1, tag="LineItem", properties={"Sku": "B"}),
        RawNode(id=2, tag="Customer", properties={"Id": "C-1"}),
    ]
    projection = RawGraphProjection(nodes=nodes, edges=[])

    by_tag = group_nodes_by_tag(projection)

    assert len(by_tag["LineItem"]) == 2
    assert len(by_tag["Customer"]) == 1


def test_group_nodes_by_tag_empty_projection_returns_empty_dict():
    assert group_nodes_by_tag(RawGraphProjection(nodes=[], edges=[])) == {}


def test_connector_yields_one_raw_record_per_node_with_matching_payload():
    nodes = [
        RawNode(id=0, tag="Contact", properties={"Id": "003CT", "FirstName": "Jane"}),
        RawNode(id=1, tag="Contact", properties={"Id": "004CT", "FirstName": "John"}),
    ]

    records = list(RawGraphConnector(nodes, tag="Contact", source_key="accounts").extract())

    assert len(records) == 2
    assert records[0].payload == {"Id": "003CT", "FirstName": "Jane"}
    assert records[1].payload == {"Id": "004CT", "FirstName": "John"}


def test_connector_stamps_source_system_and_dataset_from_tag():
    nodes = [RawNode(id=0, tag="Opportunity", properties={"Id": "006OP"})]

    [record] = list(RawGraphConnector(nodes, tag="Opportunity", source_key="accounts").extract())

    assert record.source.system == SOURCE_SYSTEM
    assert record.source.dataset == "Opportunity"


def test_connector_namespaces_record_id_with_source_key_to_avoid_cross_file_collisions():
    """Two files in the same job both produce a node id=0 for their first
    element -- record_id must stay unique across files, the same reasoning
    naming.py's raw_ws_graph/raw_workspace_id already apply to graph scope."""
    node = RawNode(id=0, tag="Account", properties={"Id": "001AC"})

    [record_a] = list(RawGraphConnector([node], tag="Account", source_key="file_a").extract())
    [record_b] = list(RawGraphConnector([node], tag="Account", source_key="file_b").extract())

    assert record_a.source.record_id != record_b.source.record_id
    assert record_a.source.record_id == "file_a:0"
    assert record_b.source.record_id == "file_b:0"


def test_connector_does_not_mutate_node_properties_dict():
    node = RawNode(id=0, tag="Account", properties={"Id": "001AC"})

    [record] = list(RawGraphConnector([node], tag="Account", source_key="f").extract())
    record.payload["Id"] = "MUTATED"

    assert node.properties["Id"] == "001AC"


def test_connector_on_empty_node_list_yields_nothing():
    assert list(RawGraphConnector([], tag="Account", source_key="f").extract()) == []


def test_parse_record_id_reverses_the_connectors_encoding():
    assert parse_record_id("accounts:0") == ("accounts", 0)


def test_parse_record_id_handles_colons_in_source_key():
    assert parse_record_id("weird:file:name:42") == ("weird:file:name", 42)


def test_parse_record_id_round_trips_with_the_connector():
    node = RawNode(id=7, tag="Account", properties={"Id": "001AC"})
    [record] = list(RawGraphConnector([node], tag="Account", source_key="my_file").extract())

    source_key, node_id = parse_record_id(record.source.record_id)

    assert source_key == "my_file"
    assert node_id == 7


def test_group_then_connect_end_to_end_against_real_projection():
    """Full slice: project real XML, group by tag, replay each tag's nodes
    through the connector -- no resolve/relate involved yet, just proving
    the two pieces compose the way the later orchestration will use them."""
    projection = _projection()
    by_tag = group_nodes_by_tag(projection)

    all_records = []
    for tag, nodes in by_tag.items():
        connector = RawGraphConnector(nodes, tag=tag, source_key="accounts")
        all_records.extend(connector.extract())

    assert len(all_records) == len(projection.nodes)
    assert {r.source.dataset for r in all_records} == set(by_tag)
