"""docs/CPQ_RULE_JOIN_DATA_CACHING_PERFORMANCE_PLAN_2026_08_10.md --
CpqEngine._load_rule_join_data now has a module-level, short-TTL cache
keyed by (workspace_id, catalog_prefix), mirroring
data_table_resolver._TABLES_CACHE's proven pattern. Confirmed live: a
single /ask HTTP turn called load_hiding_rules() + load_recommendation_
and_constraint_rules() + load_validation_rules() back to back, each
independently re-running the same 4 join-table queries from scratch.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.engine import (
    CpqEngine,
    _clear_rule_join_data_cache,
    _RULE_JOIN_DATA_CACHE_TTL_SECONDS,
)


class _CountingRdb:
    def __init__(self):
        self.calls = 0

    def fetch_rule_inputs(self, workspace_id, catalog_prefix=""):
        self.calls += 1
        return []

    def fetch_rule_actions(self, workspace_id, catalog_prefix=""):
        return []

    def fetch_marked_attrs(self, workspace_id, catalog_prefix=""):
        return []

    def fetch_rule_chain_links(self, workspace_id, catalog_prefix=""):
        return []


def test_second_call_within_ttl_hits_the_cache():
    _clear_rule_join_data_cache()
    rdb = _CountingRdb()
    eng = CpqEngine()
    with patch("aryx.cpq.engine.get_cpq_rdb", lambda: rdb):
        eng._load_rule_join_data(7, "MyCatalog")
        eng._load_rule_join_data(7, "MyCatalog")
        eng._load_rule_join_data(7, "MyCatalog")
    assert rdb.calls == 1


def test_different_workspace_id_is_a_separate_cache_key():
    _clear_rule_join_data_cache()
    rdb = _CountingRdb()
    eng = CpqEngine()
    with patch("aryx.cpq.engine.get_cpq_rdb", lambda: rdb):
        eng._load_rule_join_data(7, "MyCatalog")
        eng._load_rule_join_data(8, "MyCatalog")
    assert rdb.calls == 2


def test_different_catalog_prefix_is_a_separate_cache_key():
    _clear_rule_join_data_cache()
    rdb = _CountingRdb()
    eng = CpqEngine()
    with patch("aryx.cpq.engine.get_cpq_rdb", lambda: rdb):
        eng._load_rule_join_data(7, "CatalogA")
        eng._load_rule_join_data(7, "CatalogB")
    assert rdb.calls == 2


def test_clear_cache_forces_a_fresh_fetch():
    _clear_rule_join_data_cache()
    rdb = _CountingRdb()
    eng = CpqEngine()
    with patch("aryx.cpq.engine.get_cpq_rdb", lambda: rdb):
        eng._load_rule_join_data(7, "MyCatalog")
        _clear_rule_join_data_cache()
        eng._load_rule_join_data(7, "MyCatalog")
    assert rdb.calls == 2


def test_expired_ttl_forces_a_fresh_fetch(monkeypatch):
    """docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md widened this
    TTL from 30s to 300s -- read from the real constant rather than
    hardcoding "31.0" so this test stays correct across future TTL tuning
    instead of silently testing a value that's no longer past the TTL."""
    _clear_rule_join_data_cache()
    rdb = _CountingRdb()
    eng = CpqEngine()
    fake_time = [1000.0]
    monkeypatch.setattr("aryx.cpq.engine.time.monotonic", lambda: fake_time[0])
    with patch("aryx.cpq.engine.get_cpq_rdb", lambda: rdb):
        eng._load_rule_join_data(7, "MyCatalog")
        fake_time[0] += _RULE_JOIN_DATA_CACHE_TTL_SECONDS + 1.0  # past the TTL
        eng._load_rule_join_data(7, "MyCatalog")
    assert rdb.calls == 2


def test_second_call_within_the_new_wider_ttl_still_hits_the_cache(monkeypatch):
    """docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md -- a 60s gap
    (comfortably past the OLD 30s TTL, representative of real conversational
    pacing) must still hit the cache under the new, wider TTL."""
    _clear_rule_join_data_cache()
    rdb = _CountingRdb()
    eng = CpqEngine()
    fake_time = [1000.0]
    monkeypatch.setattr("aryx.cpq.engine.time.monotonic", lambda: fake_time[0])
    with patch("aryx.cpq.engine.get_cpq_rdb", lambda: rdb):
        eng._load_rule_join_data(7, "MyCatalog")
        fake_time[0] += 60.0
        eng._load_rule_join_data(7, "MyCatalog")
    assert rdb.calls == 1