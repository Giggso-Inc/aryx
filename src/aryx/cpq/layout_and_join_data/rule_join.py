"""``_load_rule_join_data`` -- the shared, short-TTL-cached join fetch every
rule loader builds on (Phase 4 step 5 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Needs nothing from the ``CpqEngine`` instance, so it takes no ``engine``
parameter. Every engine-module global it reads (``get_cpq_rdb``, the cache
dict, its TTL and marker holder) goes through the module object rather than
a ``from ... import`` -- ``aryx.cpq.engine.get_cpq_rdb`` is patched by dotted
path in several tests, and a frozen import-time reference would silently
bypass those patches.
"""

from __future__ import annotations

import time

from aryx.config import get_settings
from aryx.cpq import engine as _engine_module
from aryx.cpq.data_table.data_table_cache import (
    _cache_write_if_marker_unchanged,
    _invalidate_on_marker_change,
)
from aryx.cpq.rdb.rdb import PostgresCpqRdb


def _load_rule_join_data(
    workspace_id: int, catalog_prefix: str = "",
) -> tuple[
    PostgresCpqRdb,
    dict[int, list[tuple[int, str, str]]],
    dict[int, list[tuple[int, int, str, int, int, str]]],
    dict[int, list[int]],
    dict[int, int],
]:
    """Shared fetch for the rule loaders.

    BmConfigRuleInput/Action rows reference their rule by the BM-native
    rule id (``bm_config_rule_id`` from the source XML), NOT by the aryx
    entity id — the join key is the rule entity's own attrs ``id``.
    Returns (rdb, inputs_by_rule, actions_by_rule, marked_by_rule,
    chain_by_rule).

    catalog_prefix — restricts every join table to one ingested catalog.
    Required whenever a workspace holds more than one product's XML
    export: BM-native rule ids are only unique WITHIN one source, so two
    catalogs sharing a workspace can and do collide on the same native
    id (confirmed live — e.g. id 213876892 exists in both an APX Next
    and an SL3500e export). Without this, inputs_by_rule/actions_by_rule
    etc. silently merge rows from both catalogs under the same key, and
    whichever catalog's row is read last wins — corrupting rule
    evaluation even after fetch_rules() itself is correctly scoped.

    inputs_by_rule holds ALL of a rule's bm_config_rule_input rows, not
    just one — confirmed live 445/688 real rules in one catalog carry
    2+ input rows; keeping only the last (the previous behavior) meant
    63% of declarative rules with any condition were either dead
    (last-kept row's value blank) or silently over-firing (a real
    second condition dropped). See docs/CPQ_APX_NEXT_RULE_CATALOG.md
    "Gap Deep-Dive & Impact Analysis" and bml.evaluate_declarative_conditions
    for the AND/OR-grouping semantics applied to this list.

    docs/CPQ_RULE_JOIN_DATA_CACHING_PERFORMANCE_PLAN_2026_08_10.md —
    module-level, short-TTL cached (see engine._RULE_JOIN_DATA_CACHE):
    this is the shared fetch every rule loader (load_hiding_rules,
    _load_value_rules, and everything built on top of them) calls
    independently, with zero caching previously — confirmed live 3+
    redundant full re-fetches of the same join data from one turn's
    single top-level rule-loading block.
    """
    _cache = _engine_module._RULE_JOIN_DATA_CACHE
    _use_expr = get_settings().cpq_condition_expression_enabled
    _key = (workspace_id, catalog_prefix, _use_expr)
    _marker_at_read = _invalidate_on_marker_change(
        _cache, _engine_module._RULE_JOIN_DATA_CACHE_LAST_SEEN_MARKER,
    )
    _hit = _cache.get(_key)
    if _hit is not None:
        _ts, _result = _hit
        if time.monotonic() - _ts < _engine_module._RULE_JOIN_DATA_CACHE_TTL_SECONDS:
            return _result

    rdb = _engine_module.get_cpq_rdb()
    # (attr_id, value, operator) — operator is the raw BM-native
    # comparison code ("1"/"2"/.../"8"); see docs/CPQ_DECLARATIVE_
    # CONDITION_OPERATOR_PLAN_2026_08_05.md for what each means and
    # bml.evaluate_declarative_conditions for where it's interpreted.
    inputs_by_rule: dict[int, list[tuple[int, str, str]]] = {}
    for rid, aid, val, op in rdb.fetch_rule_inputs(workspace_id, catalog_prefix):
        inputs_by_rule.setdefault(rid, []).append((aid, val, op))
    if _use_expr:    # plan F3: keep each rule's condition_expression with its rows
        from aryx.cpq.layout_and_join_data.rule_expressions import attach_expressions
        inputs_by_rule = attach_expressions(rdb, workspace_id, catalog_prefix, inputs_by_rule)
    actions_by_rule: dict[int, list[tuple[int, int, str, int, int, str]]] = {}
    for rid, aid, at, val, fn, st, comments in rdb.fetch_rule_actions(workspace_id, catalog_prefix):
        actions_by_rule.setdefault(rid, []).append((aid, at, val, fn, st, comments))
    # bm_config_marked_attr: the real target linkage for many declarative
    # hiding rules — verified against real data where BmConfigRuleAction
    # and the rule's own attr_id both carry no target (docs/CPQ_GRAPH_FIX_PLAN.md §6a).
    marked_by_rule: dict[int, list[int]] = {}
    for rid, aid in rdb.fetch_marked_attrs(workspace_id, catalog_prefix):
        marked_by_rule.setdefault(rid, []).append(aid)
    # bm_config_rule_assoc: some rules chain to a child rule rather than
    # declaring their own target; the terminal rule holds the real one.
    chain_by_rule: dict[int, int] = {}
    for rid, cid in rdb.fetch_rule_chain_links(workspace_id, catalog_prefix):
        chain_by_rule[rid] = cid
    _result = (rdb, inputs_by_rule, actions_by_rule, marked_by_rule, chain_by_rule)
    _cache_write_if_marker_unchanged(
        _cache, _key, (time.monotonic(), _result), _marker_at_read,
    )
    return _result
