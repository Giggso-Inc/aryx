"""An attribute's menu items sit behind a Children wrapper in a graph built from the raw XML; the engine must find them."""
from __future__ import annotations

from unittest.mock import MagicMock

from aryx.cpq.children_wrappers import is_children_wrapper, through_children_wrappers
from aryx.cpq.product_config.product_config_menu_base import collect_base_menu_neighbors


def _n(eid, kind, direction="out", name=""):
    return {"id": eid, "type": kind, "name": name, "attributes": {}, "relationship": "CONTAINS", "direction": direction}


class _Reader:
    """attribute 1 -> own wrapper 10 -> menu items 21, 22; attribute 1 sits in its parent's wrapper 90."""

    def __init__(self, graph):
        self.graph, self.batches = graph, []

    def neighbors_batch(self, ids):
        self.batches.append(list(ids))
        return {i: list(self.graph.get(i, [])) for i in ids}


GRAPH = {
    1: [_n(10, "ApxNextChildren"), _n(90, "ApxNextChildren", "in")],
    10: [_n(21, "ApxNextBmMenuItem"), _n(22, "ApxNextBmMenuItem"), _n(1, "ApxNextBmConfigAttr", "in")],
    90: [_n(1, "ApxNextBmConfigAttr"), _n(2, "ApxNextBmConfigAttr"), _n(77, "ApxNextBmMenuItem")],   # a sibling's item: never ours
}


def test_wrapper_detection_covers_both_spellings_and_only_contained_wrappers():
    assert is_children_wrapper(_n(1, "ApxNextChildren")) and is_children_wrapper(_n(1, "_children"))
    assert is_children_wrapper({"id": 1, "type": "ApxNextChildren"})            # a reader without a direction
    assert not is_children_wrapper(_n(1, "ApxNextChildren", "in"))              # the wrapper that contains the node
    assert not is_children_wrapper(_n(1, "ApxNextBmMenuItem"))


def test_menu_items_behind_the_attributes_own_wrapper_are_added_and_nothing_else():
    reader = _Reader(GRAPH)
    out = through_children_wrappers(reader, reader.neighbors_batch([1]))
    assert [n["id"] for n in out[1]] == [10, 90, 21, 22]          # 21, 22 from its wrapper; the parent's 77 is not pulled in
    assert reader.batches == [[1], [10]]                          # one extra lookup, for the contained wrapper only


def test_a_graph_without_wrappers_is_returned_unchanged():
    reader = _Reader({1: [_n(5, "ApxNextBmMenuItem")]})
    before = reader.neighbors_batch([1])
    assert through_children_wrappers(reader, before) is before
    assert reader.batches == [[1]]                                  # no second lookup at all


def test_a_failing_second_lookup_keeps_the_direct_neighbours():
    class Broken(_Reader):
        def neighbors_batch(self, ids):
            if ids != [1]:
                raise RuntimeError("db hiccup")
            return super().neighbors_batch(ids)
    reader = Broken(GRAPH)
    before = reader.neighbors_batch([1])
    assert through_children_wrappers(reader, before) is before


def test_many_wrappers_are_looked_up_in_chunks():
    big = {i: [_n(1000 + i, "_children")] for i in range(1, 901)}
    reader = _Reader(big)
    through_children_wrappers(reader, {i: big[i] for i in big})
    assert [len(b) for b in reader.batches] == [400, 400, 100]


def test_the_engines_menu_collection_now_finds_options_behind_the_wrapper():
    reader = _Reader(GRAPH)
    attr_ents = [{"id": 1, "type": "ApxNextBmConfigAttr", "name": "Region"}]
    neighbor_map, menu_ids, orphans = collect_base_menu_neighbors(reader, attr_ents, {1: {"menu_type": "1"}}, "ApxNext")
    assert neighbor_map == {1: [21, 22]} and menu_ids == [21, 22] and orphans == []


def test_the_engines_menu_collection_is_unchanged_for_direct_menu_items():
    reader = _Reader({1: [_n(5, "ApxNextBmMenuItem"), _n(6, "ApxNextBmMenuItem")]})
    attr_ents = [{"id": 1, "type": "ApxNextBmConfigAttr", "name": "Region"}]
    neighbor_map, menu_ids, _ = collect_base_menu_neighbors(reader, attr_ents, {1: {}}, "ApxNext")
    assert neighbor_map == {1: [5, 6]} and menu_ids == [5, 6]


def test_the_product_option_fetch_also_looks_behind_the_wrapper():
    from aryx.cpq.nl_hint_extraction import product_option_fetch as pof

    reader = MagicMock()
    reader.find_entities.return_value = [{"id": 1, "name": "productSelectionProduct_all"}]
    reader.neighbors.return_value = [_n(10, "ApxNextChildren")]
    reader.neighbors_batch.return_value = {10: [_n(21, "ApxNextBmMenuItem"), _n(1, "ApxNextBmConfigAttr", "in")]}
    engine = MagicMock()
    engine._batch_fetch.side_effect = lambda ids, ws: (
        {1: {"variable_name": "productSelectionProduct_all"}} if ids == [1] else {21: {"item_value": "APX NEXT", "item_text": "APX NEXT"}})
    assert pof.fetch_product_option_list(engine, reader, 7, "ApxNext") == [("APX NEXT", "APX NEXT")]
