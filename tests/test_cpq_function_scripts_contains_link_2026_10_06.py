"""fetch_function_scripts falls back to the ScriptText entity a function CONTAINS.

Workspace 1126 (2026-10-06): 929 BmFunction entities, none with script_text;
the scripts sit on 666 ...ScriptText entities linked by 929 CONTAINS rows in
aryx_relationship. Before this fix the engine found no scripts at all.
"""
from __future__ import annotations

import json

import pytest

from aryx.cpq.rdb import rdb_postgres
from aryx.cpq.rdb.rdb import OracleCpqRdb, PostgresCpqRdb

_SENTINEL = "SENTINEL_SCRIPT_BODY_7f3a"


def _rdb(monkeypatch, functions, linked, calls=None):
    """PostgresCpqRdb with both entity reads faked."""
    rdb = PostgresCpqRdb()

    def _fake_type(workspace_id, type_suffix, catalog_prefix=""):
        assert type_suffix == "bmfunction"
        return list(functions)

    def _fake_contained(workspace_id, target_suffix, catalog_prefix=""):
        if calls is not None:
            calls.append((workspace_id, target_suffix, catalog_prefix))
        return list(linked)

    monkeypatch.setattr(rdb, "fetch_entities_by_type", _fake_type)
    monkeypatch.setattr(rdb, "fetch_contained_entities", _fake_contained)
    return rdb


@pytest.fixture
def recs(monkeypatch):
    """Raven records emitted by rdb_postgres."""
    out: list[dict] = []

    def fake(level, criticality, message, **kw):
        out.append({"level": level, "message": message, "context": kw.get("context") or {}})
        return {}

    monkeypatch.setattr(rdb_postgres, "raven_log", fake)
    return out


def test_own_script_wins_and_link_is_not_queried(monkeypatch, recs):
    calls: list = []
    rdb = _rdb(monkeypatch, [(10, {"id": "501", "script_text": "own()"})],
               [(10, 90, {"text": "linked()"})], calls)
    assert rdb.fetch_function_scripts(1126, "Apx") == {501: "own()"}
    assert calls == []
    assert recs == []


def test_missing_script_read_from_linked_scripttext(monkeypatch, recs):
    calls: list = []
    rdb = _rdb(monkeypatch, [(10, {"id": "501"})], [(10, 90, {"text": "linked()"})], calls)
    assert rdb.fetch_function_scripts(1126, "ApxnextCnofigdata") == {501: "linked()"}
    assert calls == [(1126, "scripttext", "ApxnextCnofigdata")]


def test_two_functions_share_one_merged_script_entity(monkeypatch, recs):
    rdb = _rdb(monkeypatch, [(10, {"id": "501"}), (11, {"bm_function_id": "502"})],
               [(10, 90, {"text": "same()"}), (11, 90, {"text": "same()"})])
    assert rdb.fetch_function_scripts(1126) == {501: "same()", 502: "same()"}


def test_function_without_link_stays_missing(monkeypatch, recs):
    rdb = _rdb(monkeypatch, [(10, {"id": "501"}), (11, {"id": "502"})],
               [(10, 90, {"text": "a()"})])
    assert rdb.fetch_function_scripts(1126) == {501: "a()"}
    ctx = recs[0]["context"]
    assert (ctx["without_own_script"], ctx["filled_from_link"], ctx["still_missing"]) == (2, 1, 1)


def test_own_script_not_overridden_by_link(monkeypatch, recs):
    rdb = _rdb(monkeypatch, [(10, {"id": "501", "script_text": "own()"}), (11, {"id": "502"})],
               [(10, 90, {"text": "other()"}), (11, 91, {"text": "b()"})])
    assert rdb.fetch_function_scripts(1126) == {501: "own()", 502: "b()"}


def test_first_non_blank_link_wins_in_order(monkeypatch, recs):
    rdb = _rdb(monkeypatch, [(10, {"id": "501"})],
               [(10, 90, {"text": "   "}), (10, 91, {"text": "first()"}), (10, 92, {"text": "second()"})])
    assert rdb.fetch_function_scripts(1126) == {501: "first()"}


def test_links_from_non_function_sources_are_ignored(monkeypatch, recs):
    rdb = _rdb(monkeypatch, [(10, {"id": "501"})], [(77, 90, {"text": "rule_script()"})])
    assert rdb.fetch_function_scripts(1126) == {}
    assert recs[0]["context"]["selected_option"] == "none_found"


def test_log_record_has_counts_not_script_text(monkeypatch, recs):
    rdb = _rdb(monkeypatch, [(10, {"id": "501"})], [(10, 90, {"text": _SENTINEL})])
    rdb.fetch_function_scripts(1126, "Apx")
    assert len(recs) == 1
    rec = recs[0]
    assert rec["level"] == "INFO"
    assert rec["context"]["selected_option"] == "contains_link"
    assert rec["context"]["filled_from_link"] == 1
    assert _SENTINEL not in json.dumps(rec)


class _Cur:
    def __init__(self, rows):
        self.rows, self.sql, self.params = rows, None, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.sql, self.params = sql, params

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self.cur


@pytest.mark.parametrize("cls,bind", [(PostgresCpqRdb, "%s"), (OracleCpqRdb, ":3")])
def test_fetch_contained_entities_sql_and_rows(monkeypatch, cls, bind):
    cur = _Cur([("10", "90", json.dumps({"text": "x()"}))])
    rdb = cls()
    monkeypatch.setattr(rdb, "_connection", lambda: _Conn(cur))
    rows = rdb.fetch_contained_entities(1126, "scripttext", "ApxnextCnofigdata")
    assert rows == [(10, 90, {"text": "x()"})]
    assert "aryx_relationship" in cur.sql and "aryx_entity" in cur.sql and bind in cur.sql
    assert cur.params == (1126, "CONTAINS", "apxnextcnofigdata%scripttext")


def test_fetch_contained_entities_failure_returns_empty(monkeypatch):
    rdb = OracleCpqRdb()

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(rdb, "_connection", _boom)
    assert rdb.fetch_contained_entities(1126, "scripttext") == []
