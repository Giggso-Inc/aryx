"""value_wrapper.py -- the raw-graph port of ``_xml_to_csvs``'s locale-wrapper
flattening and ``_alias_name`` name promotion (docs/ingestion/
CPQ_XML_DISPLAY_NAMES_PLAN_2026-10-05.md).

Shapes below are what ``fold_structural_leaf_tags`` (pass 1) leaves behind
for real Oracle CPQ exports, confirmed live on workspace 1126:
``<label><en>ASTRO®25_BOM</en></label>`` -> a ``label`` node with
``{"en": "ASTRO®25_BOM"}`` and no children left.
"""
from __future__ import annotations

from aryx.cpq_ingestion.constants import RAW_PROP_TEXT
from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawNode
from aryx.cpq_ingestion.raw_graph.value_wrapper import (
    apply_display_fields,
    fold_value_wrapper_tags,
    wrapper_value,
)


def _edge(src: int, tgt: int) -> RawEdge:
    return RawEdge(source_id=src, target_id=tgt, name="CONTAINS")


def _family_with_label(label_props: dict) -> tuple[RawNode, RawNode, list[RawEdge]]:
    parent = RawNode(id=1, tag="bm_prd_family", properties={"id": "17691416877"})
    label = RawNode(id=2, tag="label", properties=dict(label_props))
    return parent, label, [_edge(1, 2)]


# ── wrapper_value ────────────────────────────────────────────────────────────

def test_wrapper_value_en_preferred_over_other_locales():
    assert wrapper_value({"fr": "Bonjour", "en": "Hello"}) == "Hello"


def test_wrapper_value_no_en_falls_back_to_first_locale_in_locale_order():
    assert wrapper_value({"fr": "Bonjour", "de": "Hallo"}) == "Hallo"


def test_wrapper_value_text_only_returns_text():
    assert wrapper_value({RAW_PROP_TEXT: "plain"}) == "plain"


def test_wrapper_value_empty_en_skipped_for_next_locale():
    assert wrapper_value({"en": "  ", "de": "Hallo"}) == "Hallo"


def test_wrapper_value_nothing_usable_returns_empty_string():
    assert wrapper_value({}) == ""


# ── fold_value_wrapper_tags ──────────────────────────────────────────────────

def test_fold_label_wrapper_value_lands_on_parent_under_wrapper_tag():
    parent, label, edges = _family_with_label({"en": "ASTRO®25_BOM"})
    fold_value_wrapper_tags(edges, {"bm_prd_family": [parent], "label": [label]})
    assert parent.properties["label"] == "ASTRO®25_BOM"


def test_fold_label_wrapper_tag_removed_from_by_tag():
    parent, label, edges = _family_with_label({"en": "ASTRO®25_BOM"})
    result = fold_value_wrapper_tags(edges, {"bm_prd_family": [parent], "label": [label]})
    assert "label" not in result


def test_fold_parent_tag_kept_in_by_tag():
    parent, label, edges = _family_with_label({"en": "ASTRO®25_BOM"})
    result = fold_value_wrapper_tags(edges, {"bm_prd_family": [parent], "label": [label]})
    assert result["bm_prd_family"] == [parent]


def test_fold_mixed_text_and_locale_nodes_of_one_tag_all_fold():
    """<description> is plain text on some records and <en>-wrapped on
    others (798 nodes on ws 1126) -- pass 1 can't fold it, this pass must."""
    p1 = RawNode(id=1, tag="bm_config_attr", properties={})
    p2 = RawNode(id=2, tag="bm_config_attr", properties={})
    d1 = RawNode(id=3, tag="description", properties={RAW_PROP_TEXT: "plain text"})
    d2 = RawNode(id=4, tag="description", properties={"en": "localized"})
    fold_value_wrapper_tags([_edge(1, 3), _edge(2, 4)],
                            {"bm_config_attr": [p1, p2], "description": [d1, d2]})
    assert (p1.properties["description"], p2.properties["description"]) == ("plain text", "localized")


def test_fold_text_only_tag_with_no_locale_node_is_left_to_pass_1():
    """Plain <Customer>Bob</Customer> is a structural leaf -- pass 1's job.
    Pass 2 folding it would silently bypass ARYX_CPQ_STRUCTURAL_LEAF_FOLD_
    ENABLED=false (caught by test_structural_leaf_fold_disabled_keeps_every_
    tag_as_its_own_entity_type)."""
    parent = RawNode(id=1, tag="PurchaseOrder", properties={})
    leaf = RawNode(id=2, tag="Customer", properties={RAW_PROP_TEXT: "Bob"})
    result = fold_value_wrapper_tags([_edge(1, 2)], {"PurchaseOrder": [parent], "Customer": [leaf]})
    assert "Customer" in result


def test_fold_empty_wrapper_node_alongside_locale_nodes_folds_as_empty_string():
    """<label/> next to <label><en>X</en></label> in the same file (live:
    1 of 47 labels, 667 of 798 descriptions on ws 1126) -- pass 1 can't fold
    it (the tag isn't all-leaf), so pass 2 must, or the whole tag is skipped."""
    p1 = RawNode(id=1, tag="rec", properties={})
    p2 = RawNode(id=2, tag="rec", properties={})
    full = RawNode(id=3, tag="label", properties={"en": "X"})
    empty = RawNode(id=4, tag="label", properties={})
    result = fold_value_wrapper_tags([_edge(1, 3), _edge(2, 4)],
                                     {"rec": [p1, p2], "label": [full, empty]})
    assert "label" not in result and (p1.properties["label"], p2.properties["label"]) == ("X", "")


def test_fold_tag_with_a_real_attribute_is_not_folded():
    parent, label, edges = _family_with_label({"en": "X", "lang_id": "7"})
    result = fold_value_wrapper_tags(edges, {"bm_prd_family": [parent], "label": [label]})
    assert "label" in result


def test_fold_tag_with_a_remaining_child_is_not_folded():
    """A wrapper that still has an unfolded child in by_tag is a real
    container, not a value -- folding it would drop the child's link."""
    parent, label, edges = _family_with_label({"en": "X"})
    child = RawNode(id=3, tag="item", properties={"id": "9"})
    result = fold_value_wrapper_tags(
        edges + [_edge(2, 3)],
        {"bm_prd_family": [parent], "label": [label], "item": [child]},
    )
    assert "label" in result


def test_fold_one_non_value_node_keeps_whole_tag():
    """All-or-nothing per tag, same rule as pass 1: a tag that is sometimes
    a real record must never be half-folded."""
    p1 = RawNode(id=1, tag="rec", properties={})
    p2 = RawNode(id=2, tag="rec", properties={})
    n1 = RawNode(id=3, tag="name", properties={"en": "A"})
    n2 = RawNode(id=4, tag="name", properties={"en": "B", "code": "x"})
    result = fold_value_wrapper_tags([_edge(1, 3), _edge(2, 4)],
                                     {"rec": [p1, p2], "name": [n1, n2]})
    assert "name" in result and "name" not in p1.properties


def test_fold_parentless_wrapper_tag_kept():
    orphan = RawNode(id=5, tag="label", properties={"en": "X"})
    result = fold_value_wrapper_tags([], {"label": [orphan]})
    assert result["label"] == [orphan]


def test_fold_repeated_wrapper_under_one_parent_accumulates_list():
    parent = RawNode(id=1, tag="rec", properties={})
    a = RawNode(id=2, tag="label", properties={"en": "A"})
    b = RawNode(id=3, tag="label", properties={"en": "B"})
    fold_value_wrapper_tags([_edge(1, 2), _edge(1, 3)], {"rec": [parent], "label": [a, b]})
    assert parent.properties["label"] == ["A", "B"]


def test_fold_does_not_overwrite_existing_parent_property_silently():
    parent = RawNode(id=1, tag="rec", properties={"name": "existing"})
    wrapper = RawNode(id=2, tag="name", properties={"en": "new"})
    fold_value_wrapper_tags([_edge(1, 2)], {"rec": [parent], "name": [wrapper]})
    assert parent.properties["name"] == ["existing", "new"]


def test_fold_empty_by_tag_returns_empty():
    assert fold_value_wrapper_tags([], {}) == {}


def test_fold_node_with_no_value_properties_is_not_a_wrapper():
    """A tag whose nodes are ALL empty has no locale key anywhere -- it's a
    structural leaf (pass 1's job), not a locale wrapper."""
    parent = RawNode(id=1, tag="rec", properties={})
    empty = RawNode(id=2, tag="marker", properties={})
    result = fold_value_wrapper_tags([_edge(1, 2)], {"rec": [parent], "marker": [empty]})
    assert "marker" in result


# ── apply_display_fields ─────────────────────────────────────────────────────

def _node(props: dict) -> RawNode:
    return RawNode(id=1, tag="t", properties=dict(props))


def test_display_fields_name_promoted_from_variable_name():
    n = _node({"id": "17691416877", "variable_name": "aSTRO25_bom"})
    apply_display_fields({"t": [n]})
    assert n.properties["name"] == "aSTRO25_bom"


def test_display_fields_existing_name_not_overwritten():
    n = _node({"name": "BoolContinue1", "variable_name": "boolContinue1"})
    apply_display_fields({"t": [n]})
    assert n.properties["name"] == "BoolContinue1"


def test_display_fields_trivial_candidate_skipped():
    """_xml_to_csvs's _TRIVIAL rule: "0" must never become a name -- the
    exact value that made 430 config attrs all display as "0"."""
    n = _node({"variable_name": "0", "bm_variable_name": "aPXNext_BOM"})
    apply_display_fields({"t": [n]})
    assert n.properties["name"] == "aPXNext_BOM"


def test_display_fields_catalog_bm_variable_name_beats_bm_name_for_name():
    """Matching (catalog_naming / ingested_product_alias_map) is built on the
    variable-name shape; bm_name stays its own attribute (the alias map
    already reads it)."""
    n = _node({"bm_variable_name": "aPXNext_BOM", "bm_name": "APX™ NEXT"})
    apply_display_fields({"t": [n]})
    assert n.properties["name"] == "aPXNext_BOM"


def test_display_fields_no_candidate_leaves_name_absent():
    n = _node({"id": "1", "qty_attr_id": "0"})
    apply_display_fields({"t": [n]})
    assert "name" not in n.properties


def test_display_fields_display_label_from_label_first():
    n = _node({"label": "ASTRO®25_BOM", "bm_name": "other", "variable_name": "aSTRO25_bom"})
    apply_display_fields({"t": [n]})
    assert n.properties["display_label"] == "ASTRO®25_BOM"


def test_display_fields_display_label_from_bm_name_when_no_label():
    n = _node({"bm_name": "APX™ NEXT", "bm_variable_name": "aPXNext_BOM"})
    apply_display_fields({"t": [n]})
    assert n.properties["display_label"] == "APX™ NEXT"


def test_display_fields_no_label_source_sets_no_display_label():
    """Ask falls back to `name` when display_label is absent -- only set it
    when there is a genuinely human-readable source."""
    n = _node({"variable_name": "boolContinue1"})
    apply_display_fields({"t": [n]})
    assert "display_label" not in n.properties


def test_display_fields_list_valued_label_uses_first_non_empty():
    n = _node({"label": ["", "First"], "variable_name": "v"})
    apply_display_fields({"t": [n]})
    assert n.properties["display_label"] == "First"
