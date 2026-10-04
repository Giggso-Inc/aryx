"""xml_projector — pure unit tests against the exact sample XML used in local testing.

Node/edge counts asserted here match the live FalkorDB query results
recorded during manual local testing (see cpq_ingestion/README.md):
14 nodes / 13 edges for the plural-wrapper sample, 12 nodes / 11 edges for
the same data with wrapper tags removed.
"""
from __future__ import annotations

import logging
import tracemalloc

import pytest

from aryx.cpq_ingestion.raw_graph.xml_projector import (
    count_raw_graph_elements,
    iter_raw_graph,
    project_xml_to_raw_graph,
)
from aryx.pipeline.orchestrate import PipelineCancelled

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


def test_node_list_order_matches_id_order_for_nested_documents():
    """Regression guard: a node's RawNode is only built once its element
    *ends* (post-order), but its slot in the returned list is reserved at
    *start* time (pre-order) and filled in place -- so list order must
    match id order exactly, same as the old DOM-walk implementation.
    Without this, group_nodes_by_tag/RawGraphConnector.extract (which
    replay nodes in list order into the resolve pipeline) would see a
    different record order than before for any nested (non-flat) document."""
    projection = project_xml_to_raw_graph(WRAPPED_XML)
    assert [n.id for n in projection.nodes] == list(range(1, len(projection.nodes) + 1))


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


# ── count_raw_graph_elements -- the preview-only counter, no materialization ──
# PR #426 review: preview_raw_graph_counts() only ever used len(nodes)/
# len(edges) from the full projection, paying its full O(element count)
# memory cost (5.85M retained RawNode objects for a live 240MB upload) to
# report two integers. These tests prove the counts stay identical to the
# full projection's while never building a RawNode/RawEdge.

def test_counts_match_the_full_projection_for_wrapped_and_nowrap_xml():
    for xml in (WRAPPED_XML, NOWRAP_XML):
        projection = project_xml_to_raw_graph(xml)
        nodes, edges = count_raw_graph_elements(xml)
        assert (nodes, edges) == (len(projection.nodes), len(projection.edges))


def test_counts_match_the_full_projection_for_a_large_flat_document():
    data = _make_flat_xml(50_000)
    projection = project_xml_to_raw_graph(data)
    nodes, edges = count_raw_graph_elements(data)
    assert (nodes, edges) == (len(projection.nodes), len(projection.edges)) == (100_001, 100_000)


def test_peak_memory_does_not_scale_with_element_count():
    """The whole point: unlike project_xml_to_raw_graph (which must grow
    roughly linearly with element count since every node/edge is returned),
    a count-only pass holds no per-element output at all -- 10x more
    elements should cost near-ZERO extra memory, not even the generous
    allowance test_large_flat_document_peak_memory_scales_with_output_not_a_
    full_extra_tree gives the full projection."""
    small = _make_flat_xml(2_000)
    large = _make_flat_xml(20_000)

    tracemalloc.start()
    count_raw_graph_elements(small)
    _, peak_small = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    tracemalloc.start()
    count_raw_graph_elements(large)
    _, peak_large = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert peak_large < peak_small * 3


def test_large_document_logs_progress_and_done(caplog):
    from aryx.cpq_ingestion.raw_graph import xml_projector

    data = _make_flat_xml(60_000)  # > _PROGRESS_LOG_INTERVAL (50,000) nodes
    with caplog.at_level(logging.INFO, logger=xml_projector.__name__):
        count_raw_graph_elements(data)
    assert any("element(s) processed" in r.message for r in caplog.records)
    assert any("done" in r.message for r in caplog.records)


def test_should_stop_cancels_the_count_early(monkeypatch):
    """count_raw_graph_elements's should_stop is checked at the progress-log
    cadence -- a cancel must stop the walk with a partial, smaller count
    rather than running to completion. (project_xml_to_raw_graph, the full
    projection used at Confirm time, gained the same should_stop support in
    PR #429 -- see the tests below -- but raises instead of returning a
    partial result, since a partial RawGraphProjection would be silently
    wrong input to the resolve pipeline; a partial preview count here is
    still a reasonable answer.)"""
    from aryx.cpq_ingestion.raw_graph import xml_projector

    monkeypatch.setattr(xml_projector, "_PROGRESS_LOG_INTERVAL", 2)
    data = _make_flat_xml(50)  # 101 elements total if uninterrupted

    calls = {"n": 0}

    def _should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] >= 2  # stop on the second progress checkpoint

    nodes, edges = count_raw_graph_elements(data, should_stop=_should_stop)

    assert calls["n"] >= 2
    assert nodes < 101
    assert edges < 100


def test_should_stop_never_called_when_it_always_returns_false():
    """The common (no-cancel) case must still produce the full, correct
    count -- should_stop being wired in must not change behavior when
    nothing ever asks to stop."""
    data = _make_flat_xml(10)
    nodes, edges = count_raw_graph_elements(data, should_stop=lambda: False)
    assert (nodes, edges) == (21, 20)


# ── project_xml_to_raw_graph's own should_stop (PR #429 review: the
# Confirm-stage cpq_ingestion loop calls this full projection before
# resolve_and_relate_raw_graph's per-tag checks can help, so the whole
# ~40-78s parse was uncancellable until this) ──────────────────────────────

def test_project_raises_pipeline_cancelled_instead_of_returning_partial(monkeypatch):
    """Unlike count_raw_graph_elements (a preview where a partial answer is
    fine), a partial RawGraphProjection would be silently wrong input to
    the resolve pipeline -- cancellation here must raise, not return early."""
    from aryx.cpq_ingestion.raw_graph import xml_projector

    monkeypatch.setattr(xml_projector, "_PROGRESS_LOG_INTERVAL", 2)
    data = _make_flat_xml(50)

    with pytest.raises(PipelineCancelled):
        project_xml_to_raw_graph(data, should_stop=lambda: True)


def test_project_should_stop_false_behaves_exactly_as_before(monkeypatch):
    from aryx.cpq_ingestion.raw_graph import xml_projector

    monkeypatch.setattr(xml_projector, "_PROGRESS_LOG_INTERVAL", 2)
    data = _make_flat_xml(50)

    projection = project_xml_to_raw_graph(data, should_stop=lambda: False)
    assert len(projection.nodes) == 101
    assert len(projection.edges) == 100


def test_project_default_should_stop_none_is_unaffected():
    """Regression guard: every pre-existing caller omits should_stop."""
    projection = project_xml_to_raw_graph(WRAPPED_XML)
    assert len(projection.nodes) == 14
    assert len(projection.edges) == 13


# ── iter_raw_graph (§3b, 2026-10-04) — equivalence with the eager function ──

def _drain(data: bytes, **kwargs):
    nodes = []
    edges = []
    for node, edge in iter_raw_graph(data, **kwargs):
        nodes.append(node)
        if edge is not None:
            edges.append(edge)
    return nodes, edges


def _as_sorted_by_id(nodes):
    return sorted(nodes, key=lambda n: n.id)


def _as_sorted_edges(edges):
    return sorted(edges, key=lambda e: e.target_id)


def test_iter_matches_eager_nodes_and_edges_for_wrapped_xml():
    """Same SET of nodes/edges as the eager function -- not the same list
    ORDER, since iter_raw_graph yields in finish-order (post-order) while
    project_xml_to_raw_graph's list is id-ordered (pre-order); see
    iter_raw_graph's docstring for why that's fine for every real caller."""
    projection = project_xml_to_raw_graph(WRAPPED_XML)
    nodes, edges = _drain(WRAPPED_XML)

    assert _as_sorted_by_id(nodes) == _as_sorted_by_id(projection.nodes)
    assert _as_sorted_edges(edges) == _as_sorted_edges(projection.edges)


def test_iter_matches_eager_nodes_and_edges_for_nowrap_xml():
    projection = project_xml_to_raw_graph(NOWRAP_XML)
    nodes, edges = _drain(NOWRAP_XML)

    assert _as_sorted_by_id(nodes) == _as_sorted_by_id(projection.nodes)
    assert _as_sorted_edges(edges) == _as_sorted_edges(projection.edges)


def test_iter_matches_eager_for_a_large_flat_document():
    data = _make_flat_xml(500)
    projection = project_xml_to_raw_graph(data)
    nodes, edges = _drain(data)

    assert _as_sorted_by_id(nodes) == _as_sorted_by_id(projection.nodes)
    assert _as_sorted_edges(edges) == _as_sorted_edges(projection.edges)


def test_iter_root_node_has_no_edge():
    """The root is yielded LAST (post-order), not first -- find it by
    id==1 (always the first element to *start*, regardless of when it's
    yielded) rather than assuming yield position."""
    pairs = list(iter_raw_graph(WRAPPED_XML))
    root_pairs = [(n, e) for n, e in pairs if n.id == 1]
    assert len(root_pairs) == 1
    root_node, root_edge = root_pairs[0]
    assert root_node.tag == "Accounts"
    assert root_edge is None


def test_iter_every_non_root_node_has_exactly_one_edge_to_its_parent():
    pairs = list(iter_raw_graph(WRAPPED_XML))
    for node, edge in pairs:
        if node.id == 1:
            continue  # root, covered by test_iter_root_node_has_no_edge
        assert edge is not None
        assert edge.target_id == node.id


def test_iter_preserves_relative_order_among_same_tag_siblings():
    """The guarantee that actually matters downstream (per-tag grouping
    order, entity-id assignment / merge tie-breaks): two same-tag
    elements that are siblings (not nested in each other) must still
    yield in left-to-right document order, even though overall yield
    order is post-order, not id-order."""
    xml = b"""<Root>
      <Item>first</Item>
      <Item>second</Item>
      <Item>third</Item>
    </Root>"""
    nodes, _ = _drain(xml)
    items = [n for n in nodes if n.tag == "Item"]
    assert [n.properties["text"] for n in items] == ["first", "second", "third"]


def test_iter_raises_pipeline_cancelled_like_the_eager_function(monkeypatch):
    from aryx.cpq_ingestion.raw_graph import xml_projector

    monkeypatch.setattr(xml_projector, "_PROGRESS_LOG_INTERVAL", 2)
    data = _make_flat_xml(50)

    with pytest.raises(PipelineCancelled):
        list(iter_raw_graph(data, should_stop=lambda: True))


def test_iter_should_stop_false_behaves_exactly_as_before(monkeypatch):
    from aryx.cpq_ingestion.raw_graph import xml_projector

    monkeypatch.setattr(xml_projector, "_PROGRESS_LOG_INTERVAL", 2)
    data = _make_flat_xml(50)

    nodes, edges = _drain(data, should_stop=lambda: False)
    assert len(nodes) == 101
    assert len(edges) == 100


def test_iter_peak_memory_does_not_scale_with_element_count():
    """The whole point of §3b: iter_raw_graph's OWN peak memory (not
    counting whatever the caller chooses to retain from the yielded
    stream) must stay roughly constant regardless of document size.
    Critically, this must DRAIN the generator without accumulating
    results into a list -- list(iter_raw_graph(...)) would measure the
    drained list's memory, not the generator's own walk memory, exactly
    the "whatever the caller chooses to retain" the docstring warns is a
    separate concern. Mirrors
    test_peak_memory_does_not_scale_with_element_count for
    count_raw_graph_elements below, same measurement technique."""
    small = _make_flat_xml(2_000)
    large = _make_flat_xml(20_000)

    tracemalloc.start()
    for _ in iter_raw_graph(small):
        pass
    _, small_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    tracemalloc.start()
    for _ in iter_raw_graph(large):
        pass
    _, large_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # 10x more elements must not come anywhere near 10x the peak --
    # generous bound (not a tight regression test) to avoid flaking on
    # unrelated interpreter/allocator noise.
    assert large_peak < small_peak * 5
