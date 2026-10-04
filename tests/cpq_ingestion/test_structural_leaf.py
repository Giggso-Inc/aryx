"""structural_leaf.py -- §1 Tier 1 classification/folding, plus PR review
M4 (performance) and N2 (empty-text leaf) fixes. No coverage existed for
this module before (PR review N1)."""
from __future__ import annotations

from aryx.cpq_ingestion.constants import RAW_PROP_TEXT
from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawGraphProjection, RawNode
from aryx.cpq_ingestion.raw_graph.structural_leaf import (
    fold_structural_leaf_tags,
    is_structural_leaf_tag,
)


def _leaf(node_id: int, text: str | None) -> RawNode:
    props = {RAW_PROP_TEXT: text} if text is not None else {}
    return RawNode(id=node_id, tag="id", properties=props)


# ── is_structural_leaf_tag ───────────────────────────────────────────────────

def test_leaf_with_only_text_property_classifies_as_leaf():
    nodes = [RawNode(id=1, tag="id", properties={RAW_PROP_TEXT: "123"})]
    assert is_structural_leaf_tag(nodes, parent_ids=set()) is True


def test_node_with_a_real_attribute_is_not_a_leaf():
    """A real XML attribute alongside RAW_PROP_TEXT must disqualify the tag
    -- the naive 'properties is non-empty' check this replaced would have
    never fired at all, since every leaf's properties dict already has
    RAW_PROP_TEXT in it."""
    nodes = [RawNode(id=1, tag="PurchaseOrder", properties={"Id": "PO-1", RAW_PROP_TEXT: "text"})]
    assert is_structural_leaf_tag(nodes, parent_ids=set()) is False


def test_node_with_no_properties_at_all_is_still_a_leaf():
    nodes = [RawNode(id=1, tag="flag", properties={})]
    assert is_structural_leaf_tag(nodes, parent_ids=set()) is True


def test_node_that_has_children_is_not_a_leaf():
    nodes = [RawNode(id=1, tag="Record", properties={})]
    assert is_structural_leaf_tag(nodes, parent_ids={1}) is False


def test_any_node_of_the_tag_with_children_disqualifies_the_whole_tag():
    nodes = [RawNode(id=1, tag="id", properties={RAW_PROP_TEXT: "a"}),
             RawNode(id=2, tag="id", properties={RAW_PROP_TEXT: "b"})]
    assert is_structural_leaf_tag(nodes, parent_ids={2}) is False


# ── fold_structural_leaf_tags: basic correctness ─────────────────────────────

def test_leaf_tag_value_folds_onto_parent_and_is_removed_from_by_tag():
    parent = RawNode(id=1, tag="Record", properties={})
    leaf = _leaf(2, "123")
    projection = RawGraphProjection(
        nodes=[parent, leaf],
        edges=[RawEdge(source_id=1, target_id=2, name="CONTAINS")],
    )
    by_tag = {"Record": [parent], "id": [leaf]}

    result = fold_structural_leaf_tags(projection.edges, by_tag)

    assert "id" not in result
    assert "Record" in result
    assert parent.properties["id"] == "123"


def test_non_leaf_tag_is_left_untouched():
    parent = RawNode(id=1, tag="Record", properties={})
    child = RawNode(id=2, tag="LineItem", properties={"Sku": "WIDGET-A"})
    projection = RawGraphProjection(
        nodes=[parent, child],
        edges=[RawEdge(source_id=1, target_id=2, name="CONTAINS")],
    )
    by_tag = {"Record": [parent], "LineItem": [child]}

    result = fold_structural_leaf_tags(projection.edges, by_tag)

    assert result == by_tag
    assert "Sku" not in parent.properties


def test_empty_by_tag_returns_as_is():
    projection = RawGraphProjection(nodes=[], edges=[])
    assert fold_structural_leaf_tags(projection.edges, {}) == {}


# ── multiple leaf children under one parent (same tag) ───────────────────────

def test_two_leaves_same_tag_under_one_parent_accumulate_a_list():
    parent = RawNode(id=1, tag="Record", properties={})
    leaf_a = _leaf(2, "a")
    leaf_b = _leaf(3, "b")
    projection = RawGraphProjection(
        nodes=[parent, leaf_a, leaf_b],
        edges=[
            RawEdge(source_id=1, target_id=2, name="CONTAINS"),
            RawEdge(source_id=1, target_id=3, name="CONTAINS"),
        ],
    )
    by_tag = {"Record": [parent], "id": [leaf_a, leaf_b]}

    fold_structural_leaf_tags(projection.edges, by_tag)

    assert parent.properties["id"] == ["a", "b"]


def test_leaf_folding_onto_a_parent_with_an_existing_same_named_attribute():
    parent = RawNode(id=1, tag="Record", properties={"id": "real-attr"})
    leaf = _leaf(2, "leaf-value")
    projection = RawGraphProjection(
        nodes=[parent, leaf],
        edges=[RawEdge(source_id=1, target_id=2, name="CONTAINS")],
    )
    by_tag = {"Record": [parent], "id": [leaf]}

    fold_structural_leaf_tags(projection.edges, by_tag)

    assert parent.properties["id"] == ["real-attr", "leaf-value"]


# ── orphan leaves (no parent edge) -- fix keeps them in the resolve path ─────

def test_orphan_leaf_tag_is_kept_in_resolve_path_not_dropped():
    """A leaf-shaped tag with no parent edge (e.g. an XML document's root
    tag) must not be silently folded onto nothing -- that would lose the
    value outright."""
    leaf = _leaf(1, "root-value")
    projection = RawGraphProjection(nodes=[leaf], edges=[])
    by_tag = {"id": [leaf]}

    result = fold_structural_leaf_tags(projection.edges, by_tag)

    assert "id" in result
    assert result["id"] == [leaf]


# ── PR review N2: empty-text leaf must not vanish silently ───────────────────

def test_leaf_with_no_text_folds_as_empty_string_not_dropped():
    """<flag/> (no text at all) previously counted toward neither
    folded_count nor orphan_count, so the tag was marked 'fully folded'
    with zero actual folds and quietly vanished from the resolve set with
    no trace anywhere. Must fold as an empty-string property instead."""
    parent = RawNode(id=1, tag="Record", properties={})
    marker = RawNode(id=2, tag="flag", properties={})  # no RAW_PROP_TEXT at all
    projection = RawGraphProjection(
        nodes=[parent, marker],
        edges=[RawEdge(source_id=1, target_id=2, name="CONTAINS")],
    )
    by_tag = {"Record": [parent], "flag": [marker]}

    result = fold_structural_leaf_tags(projection.edges, by_tag)

    assert "flag" not in result
    assert parent.properties["flag"] == ""


# ── PR review M4: nodes_by_id is only built when something actually folds ───

def test_no_leaf_tags_returns_input_unchanged_by_identity():
    """PR review M4: when nothing in by_tag classifies as a structural
    leaf, fold_structural_leaf_tags must short-circuit and return the
    SAME object it was given, not a rebuilt copy -- the cheapest possible
    signal that the expensive nodes_by_id dict was never constructed."""
    parent = RawNode(id=1, tag="Record", properties={})
    child = RawNode(id=2, tag="LineItem", properties={"Sku": "WIDGET-A"})
    projection = RawGraphProjection(
        nodes=[parent, child],
        edges=[RawEdge(source_id=1, target_id=2, name="CONTAINS")],
    )
    by_tag = {"Record": [parent], "LineItem": [child]}

    result = fold_structural_leaf_tags(projection.edges, by_tag)

    assert result is by_tag


def test_result_is_a_new_dict_not_the_same_object_when_folding_happens():
    parent = RawNode(id=1, tag="Record", properties={})
    leaf = _leaf(2, "123")
    projection = RawGraphProjection(
        nodes=[parent, leaf],
        edges=[RawEdge(source_id=1, target_id=2, name="CONTAINS")],
    )
    by_tag = {"Record": [parent], "id": [leaf]}

    result = fold_structural_leaf_tags(projection.edges, by_tag)

    assert result is not by_tag
    assert by_tag == {"Record": [parent], "id": [leaf]}  # input untouched
