"""Regression coverage for a data-loss bug found by post-merge review.

update_entity_attributes.sql used to back two callers with mutually
incompatible contracts:
- ActionStore.set_attribute() docstring says "merge one attribute" but
  passed a single-key {key: value} dict to a query that did a full column
  REPLACE on Postgres -- silently wiping every other attribute.
- EntityStore.update_entity() docstring says "replace attributes" and
  passed the full dict, which is correct on Postgres but the Oracle
  override did a JSON_MERGEPATCH (merge), silently retaining keys the
  caller meant to remove.

Split into merge_one_attribute.sql (real merge, both backends) and
update_entity_attributes.sql (real replace, both backends).

Separately: merge_entity_attributes.sql's Oracle override had
JSON_MERGEPATCH's target/patch arguments swapped, so the about-to-be-
deleted duplicate's attribute values won over the surviving entity's on
key conflicts (JSON_MERGEPATCH(target, patch) -- patch wins), the
opposite of `src.attributes || dst.attributes`'s right-operand-wins
semantics on Postgres.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.store.action_store import ActionStore
from aryx.store.entity_store import EntityStore


def _make_pool_cursor():
    cur = MagicMock()
    cur.fetchone.return_value = None
    cur_cm = MagicMock()
    cur_cm.__enter__ = MagicMock(return_value=cur)
    cur_cm.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cur_cm)
    conn_cm = MagicMock()
    conn_cm.__enter__ = MagicMock(return_value=conn)
    conn_cm.__exit__ = MagicMock(return_value=False)
    pool = MagicMock()
    pool.connection = MagicMock(return_value=conn_cm)
    return pool, cur


def test_action_store_set_attribute_uses_merge_query_not_replace():
    pool, cur = _make_pool_cursor()
    with patch("aryx.store.action_store.get_pool", return_value=pool):
        store = ActionStore("postgresql://test", workspace_id=1)
    with patch("aryx.store.action_store.load", side_effect=lambda name: name) as mock_load:
        store.set_attribute(7, "risk_flag", "SOLE_SOURCE")
    mock_load.assert_called_once_with("merge_one_attribute")
    executed_query_name = cur.execute.call_args[0][0]
    assert executed_query_name == "merge_one_attribute"


def test_entity_store_update_entity_uses_replace_query():
    pool, cur = _make_pool_cursor()
    cur.fetchone.return_value = (7, "Widget", {"a": 1})
    with patch("aryx.store.entity_store.get_pool", return_value=pool):
        store = EntityStore("postgresql://test", workspace_id=1)
    with patch("aryx.store.entity_store.load", side_effect=lambda name: name) as mock_load:
        store.update_entity(7, {"a": 1})
    mock_load.assert_called_once_with("update_entity_attributes")


def test_merge_one_attribute_sql_merges_not_replaces():
    """Generic (Postgres) merge query must use jsonb || to merge, not
    a plain assignment that would replace the whole column."""
    sql = open("src/aryx/queries/merge_one_attribute.sql").read()
    assert "attributes ||" in sql or "|| attributes" in sql
    assert "SET attributes = %s," not in sql


def test_update_entity_attributes_sql_replaces_not_merges():
    """Generic (Postgres) replace query must be a plain assignment."""
    sql = open("src/aryx/queries/update_entity_attributes.sql").read()
    assert "SET attributes = %s" in sql
    assert "||" not in sql


def test_oracle_merge_one_attribute_uses_json_mergepatch():
    sql = open("src/aryx/queries/oracle/merge_one_attribute.sql").read()
    assert "JSON_MERGEPATCH" in sql


def test_oracle_update_entity_attributes_replaces_not_merges():
    sql = open("src/aryx/queries/oracle/update_entity_attributes.sql").read()
    assert "JSON_MERGEPATCH" not in sql
    assert "SET attributes = %s" in sql


def test_oracle_merge_entity_attributes_survivor_wins_on_conflict():
    """JSON_MERGEPATCH(target, patch) -- patch wins on key conflicts.
    To match Postgres's `src.attributes || dst.attributes` (dst/survivor
    wins), the SELECT for src (the about-to-be-deleted duplicate) must be
    the TARGET (first) argument, and dst.attributes (the survivor) must be
    the PATCH (second) argument -- so the survivor's values win."""
    sql = open("src/aryx/queries/oracle/merge_entity_attributes.sql").read()
    # Search only the actual SQL statement, not the header comment (which
    # itself contains the strings "JSON_MERGEPATCH(" and "dst.attributes"
    # in its prose explanation).
    statement = sql[sql.index("UPDATE aryx_entity dst"):]
    mergepatch_start = statement.index("JSON_MERGEPATCH(")
    args_text = statement[mergepatch_start:]
    select_src_pos = args_text.index("SELECT src.attributes")
    dst_attributes_pos = args_text.index("dst.attributes")
    assert select_src_pos < dst_attributes_pos, (
        "src (dropped duplicate) must be the JSON_MERGEPATCH target and "
        "dst (survivor) the patch, so the survivor's values win on conflict"
    )
