"""docs/FALKORDB_QUERY_EXHAUSTION_2026_08_14.md (F1) -- graph.pool caches one
adapter instance per (url, graph) instead of constructing a fresh one on
every Container.graph_reader()/.graph_store() call.
"""
from __future__ import annotations

from aryx.graph import pool


class _FakeAdapter:
    instances_created = 0

    def __init__(self, url, graph):
        self.url = url
        self.graph = graph
        _FakeAdapter.instances_created += 1


def setup_function():
    pool.clear_all()
    _FakeAdapter.instances_created = 0


def test_same_key_returns_the_same_cached_reader():
    a = pool.get_graph_reader(_FakeAdapter, "redis://x:6379", "aryx_ws_1")
    b = pool.get_graph_reader(_FakeAdapter, "redis://x:6379", "aryx_ws_1")
    assert a is b
    assert _FakeAdapter.instances_created == 1


def test_different_graph_names_get_different_readers():
    a = pool.get_graph_reader(_FakeAdapter, "redis://x:6379", "aryx_ws_1")
    b = pool.get_graph_reader(_FakeAdapter, "redis://x:6379", "aryx_ws_2")
    assert a is not b
    assert _FakeAdapter.instances_created == 2


def test_different_urls_get_different_readers_even_for_the_same_graph_name():
    a = pool.get_graph_reader(_FakeAdapter, "redis://x:6379", "aryx_ws_1")
    b = pool.get_graph_reader(_FakeAdapter, "redis://y:6379", "aryx_ws_1")
    assert a is not b


def test_reader_and_store_caches_are_independent():
    reader = pool.get_graph_reader(_FakeAdapter, "redis://x:6379", "aryx_ws_1")
    store = pool.get_graph_store(_FakeAdapter, "redis://x:6379", "aryx_ws_1")
    assert reader is not store
    assert _FakeAdapter.instances_created == 2


def test_clear_all_forces_fresh_instances_on_next_call():
    a = pool.get_graph_reader(_FakeAdapter, "redis://x:6379", "aryx_ws_1")
    pool.clear_all()
    b = pool.get_graph_reader(_FakeAdapter, "redis://x:6379", "aryx_ws_1")
    assert a is not b
    assert _FakeAdapter.instances_created == 2
