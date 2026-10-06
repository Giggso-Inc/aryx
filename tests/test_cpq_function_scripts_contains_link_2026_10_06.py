"""fetch_function_scripts falls back to the ScriptText entity a function CONTAINS.

Workspace 1126 (2026-10-06): 929 BmFunction entities, none with script_text;
the scripts sit on 666 ...ScriptText entities linked by 929 CONTAINS rows in
aryx_relationship. Before this fix the engine found no scripts at all.

PR #445 review: a merged ScriptText entity is used only when all of its
member records carry the same text (H1); the lookup is cached per workspace
and cleared on re-ingest (M1); the Raven record fires on a cache miss only (L1).
"""
from __future__ import annotations

import json

import pytest

from aryx.cpq.data_table import data_table_cache
from aryx.cpq.rdb import rdb_linked_scripts, rdb_postgres
from aryx.cpq.rdb.rdb import OracleCpqRdb, PostgresCpqRdb

_SENTINEL = "SENTINEL_SCRIPT_BODY_7f3a"
_MARKER = [100.0]


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch):
    """Fresh link cache per test; the re-ingest marker is a controllable value, no DB."""
    _MARKER[0] = 100.0
    monkeypatch.setattr(data_table_cache, "_current_invalidation_marker", lambda: _MARKER[0])
    rdb_linked_scripts.clear_linked_scripts_cache()
    yield
    rdb_linked_scripts.clear_linked_scripts_cache()


def _rdb(monkeypatch, functions, linked, members="from_links", calls=None):
    """PostgresCpqRdb with the three entity reads faked.

    members defaults to one member per linked target carrying that target's
    text (an exact-text merge); pass a list to control it, or None for a failed read.
    """
    rdb = PostgresCpqRdb()
    if members == "from_links":
        members = list({tgt: (tgt, attrs) for _src, tgt, attrs in linked}.values())

    def _fake_type(workspace_id, type_suffix, catalog_prefix=""):
        assert type_suffix == "bmfunction"
        return list(functions)

    def _fake_contained(workspace_id, target_suffix, catalog_prefix=""):
        if calls is not None:
            calls.append((workspace_id, target_suffix, catalog_prefix))
        return list(linked)

    def _fake_members(workspace_id, target_suffix, catalog_prefix=""):
        return None if members is None else list(members)

    monkeypatch.setattr(rdb, "fetch_entities_by_type", _fake_type)
    monkeypatch.setattr(rdb, "fetch_contained_entities", _fake_contained)
    monkeypatch.setattr(rdb, "fetch_member_payloads", _fake_members)
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
               [(10, 90, {"text": "linked()"})], calls=calls)
    assert rdb.fetch_function_scripts(1126, "Apx") == {501: "own()"}
    assert calls == []
    assert recs == []


def test_missing_script_read_from_linked_scripttext(monkeypatch, recs):
    calls: list = []
    rdb = _rdb(monkeypatch, [(10, {"id": "501"})], [(10, 90, {"text": "linked()"})], calls=calls)
    assert rdb.fetch_function_scripts(1126, "ApxnextCnofigdata") == {501: "linked()"}
    assert calls == [(1126, "scripttext", "ApxnextCnofigdata")]


def test_two_functions_share_one_exact_merged_entity(monkeypatch, recs):
    rdb = _rdb(monkeypatch, [(10, {"id": "501"}), (11, {"bm_function_id": "502"})],
               [(10, 90, {"text": "same()"}), (11, 90, {"text": "same()"})],
               members=[(90, {"text": "same()"}), (90, {"text": "same()"})])
    assert rdb.fetch_function_scripts(1126) == {501: "same()", 502: "same()"}


def test_entity_merging_different_texts_is_skipped(monkeypatch, recs):
    """H1: never hand a function another function's script."""
    rdb = _rdb(monkeypatch, [(10, {"id": "501"}), (11, {"id": "502"}), (12, {"id": "503"})],
               [(10, 90, {"text": "survivor()"}), (11, 90, {"text": "survivor()"}),
                (12, 91, {"text": "solo()"})],
               members=[(90, {"text": "survivor()"}), (90, {"text": "different()"}),
                        (91, {"text": "solo()"})])
    assert rdb.fetch_function_scripts(1126) == {503: "solo()"}
    ctx = recs[0]["context"]
    assert (ctx["mixed_entities"], ctx["skipped_links"], ctx["still_missing"]) == (1, 2, 2)


def test_member_check_failure_fills_nothing_and_is_not_cached(monkeypatch, recs):
    rdb = _rdb(monkeypatch, [(10, {"id": "501"})], [(10, 90, {"text": "x()"})], members=None)
    assert rdb.fetch_function_scripts(1126) == {}
    assert recs[0]["context"]["reason_code"] == "MEMBER_CHECK_FAILED"
    assert rdb_linked_scripts._CACHE == {}


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


def test_lookup_cached_and_logged_once_per_workspace(monkeypatch, recs):
    """M1 + L1: repeated calls in a turn reuse the lookup and log once."""
    calls: list = []
    rdb = _rdb(monkeypatch, [(10, {"id": "501"})], [(10, 90, {"text": "a()"})], calls=calls)
    for _ in range(4):
        assert rdb.fetch_function_scripts(1126, "Apx") == {501: "a()"}
    assert len(calls) == 1
    assert len(recs) == 1
    rdb.fetch_function_scripts(1126, "Other")
    assert len(calls) == 2  # different catalog, separate entry


def test_reingest_marker_clears_the_cache(monkeypatch, recs):
    calls: list = []
    rdb = _rdb(monkeypatch, [(10, {"id": "501"})], [(10, 90, {"text": "a()"})], calls=calls)
    rdb.fetch_function_scripts(1126)
    _MARKER[0] = 200.0
    rdb.fetch_function_scripts(1126)
    assert len(calls) == 2


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


@pytest.mark.parametrize("cls,bind", [(PostgresCpqRdb, "%s"), (OracleCpqRdb, ":2")])
def test_fetch_member_payloads_sql_and_rows(monkeypatch, cls, bind):
    cur = _Cur([("90", json.dumps({"text": "x()"}))])
    rdb = cls()
    monkeypatch.setattr(rdb, "_connection", lambda: _Conn(cur))
    assert rdb.fetch_member_payloads(1126, "scripttext", "Apx") == [(90, {"text": "x()"})]
    assert "aryx_entity_member" in cur.sql and "aryx_landed_record" in cur.sql and bind in cur.sql
    assert cur.params == (1126, "apx%scripttext")


@pytest.mark.parametrize("cls", [PostgresCpqRdb, OracleCpqRdb])
def test_read_failures(monkeypatch, cls):
    rdb = cls()

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(rdb, "_connection", _boom)
    assert rdb.fetch_contained_entities(1126, "scripttext") == []
    assert rdb.fetch_member_payloads(1126, "scripttext") is None
