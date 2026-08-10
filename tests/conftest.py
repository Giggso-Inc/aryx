"""Shared, session-wide pytest fixtures.

docs/CPQ_RULE_JOIN_DATA_CACHING_PERFORMANCE_PLAN_2026_08_10.md — CpqEngine.
_load_rule_join_data now has a module-level, short-TTL cache keyed by
(workspace_id, catalog_prefix). Left uncleared between tests, one test's
monkeypatched RDB rule data could leak into another test reusing the same
key with different data. Autouse + global (not per-file) because dozens of
existing test files across this suite already call load_hiding_rules/
_load_value_rules/load_recommendation_and_constraint_rules with
monkeypatched fixtures predating this cache's existence.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_rule_join_data_cache_between_tests():
    from aryx.cpq.engine import _clear_rule_join_data_cache

    _clear_rule_join_data_cache()
    yield
    _clear_rule_join_data_cache()
