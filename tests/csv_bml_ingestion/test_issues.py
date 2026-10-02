"""Stored CSV issues: collecting rejected rows, the issue store, re-running, the API, upload recording."""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from aryx.csv_bml_ingestion import issue_store as st
from aryx.csv_bml_ingestion import ingest_csv
from aryx.csv_bml_ingestion.csv_reader import CsvStats, iter_numbered_rows, read_layout
from aryx.csv_bml_ingestion.errors import TableProtectedError
from aryx.csv_bml_ingestion.issue_store import IssueStore, should_record
from aryx.csv_bml_ingestion.options import IngestResult
from aryx.csv_bml_ingestion.overflow import OverflowPolicy
from aryx.csv_bml_ingestion.rejects import RejectCollector, RejectedRow
from aryx.csv_bml_ingestion.rerun import RerunError, rerun_rejects

from .conftest import FakeCursor, FakeDb, write_csv
from .test_pipeline import SEQ_HEADER, _seq_csv


# ------------------------------------------------------------------ a DB that also understands the issue tables
class IssueCursor(FakeCursor):
    def __init__(self, db):
        super().__init__(db.log, db.catalog, db.comments)
        self.db = db
        self.rowcount = 0

    def execute(self, sql, params=None):
        d = self.db
        if "aryx_csv_ingest" not in sql:
            return super().execute(sql, params)
        d.log.append(("execute", sql))
        p = params or ()
        if sql.startswith("INSERT INTO aryx_csv_ingest_run"):
            keys = ("run_id", "workspace_id", "job_id", "source_file", "table_name", "status", "error_code", "message",
                    "rows_loaded", "rows_bad", "rows_rejected", "rows_truncated", "reject_total", "reject_stored",
                    "file_size", "file_gz_b64", "rerun_of", "state", "logical_table")
            d.runs[p[0]] = {**dict(zip(keys, p)), "created_at": f"2026-10-02T00:00:{len(d.runs):02d}"}
        elif sql.startswith("SELECT run_id, job_id") and "AND run_id = %s" in sql:
            self._rows = [d.run_tuple(r) for r in d.runs.values() if r["workspace_id"] == p[0] and r["run_id"] == p[1]]
        elif sql.startswith("SELECT run_id, job_id"):
            lim = int(re.search(r"FETCH FIRST (\d+)", sql).group(1))
            rows = [r for r in d.runs.values() if r["workspace_id"] == p[0] and (len(p) < 2 or r["job_id"] == p[1])]
            self._rows = [d.run_tuple(r) for r in sorted(rows, key=lambda r: r["created_at"], reverse=True)][:lim]
        elif sql.startswith("SELECT source_file, file_gz_b64"):
            r = d.runs.get(p[1])
            self._rows = [(r["source_file"], r["file_gz_b64"])] if r and r["workspace_id"] == p[0] else []
        elif sql.startswith("SELECT reject_id, line_no, reason_code, reason"):
            off, lim = (int(x) for x in re.search(r"OFFSET (\d+) ROWS FETCH NEXT (\d+)", sql).groups())
            rows = [x for x in d.rejects if x["workspace_id"] == p[0] and x["run_id"] == p[1] and (len(p) < 3 or x["state"] == p[2])]
            self._rows = [(x["reject_id"], x["line_no"], x["reason_code"], x["reason"], x["row_json"], x["state"],
                           x["attempts"], None) for x in rows][off:off + lim]
        elif sql.startswith("UPDATE aryx_csv_ingest_run SET state = 'superseded'") and "source_file" in sql:
            ws, source, keep, table = p
            for r in d.runs.values():
                if (r["workspace_id"] == ws and r["source_file"] == source and r["state"] == "open"
                        and r["run_id"] != keep and r["table_name"] in (None, table)
                        and ("status <> 'loaded'" not in sql or r["status"] != "loaded")):
                    r["state"] = "superseded"
        elif sql.startswith("UPDATE aryx_csv_ingest_run SET state = 'superseded'"):
            r = d.runs.get(p[1])
            hit = bool(r and r["workspace_id"] == p[0] and r["state"] == "open")
            if hit:
                r["state"] = "superseded"
            self.rowcount = 1 if hit else 0
        elif sql.startswith("UPDATE aryx_csv_ingest_run SET state") and "IN ('open', 'resolved')" in sql:
            r = d.runs.get(p[2])
            if r and r["workspace_id"] == p[1] and r["state"] in ("open", "resolved"):
                r["state"] = p[0]
        elif sql.startswith("UPDATE aryx_csv_ingest_run SET state"):
            r = d.runs.get(p[2])
            if r and r["workspace_id"] == p[1]:
                r["state"] = p[0]
        elif sql.startswith("DELETE FROM aryx_csv_ingest_run"):
            for rid in [k for k, r in d.runs.items() if not p or r["workspace_id"] == p[0]]:
                d.runs.pop(rid)
                d.rejects[:] = [x for x in d.rejects if x["run_id"] != rid]
        elif "SET state = 'retrying'" in sql:
            for x in d.rejects:
                if (x["workspace_id"] == p[0] and x["run_id"] == p[1] and x["state"] == "open"
                        and d.runs[x["run_id"]]["state"] != "superseded"):
                    x["state"] = "retrying"
        elif sql.startswith("SELECT reject_id, line_no, reason_code, row_json"):
            self._rows = [(x["reject_id"], x["line_no"], x["reason_code"], x["row_json"]) for x in d.rejects
                          if x["workspace_id"] == p[0] and x["run_id"] == p[1] and x["state"] == "retrying"]
        elif sql.startswith("SELECT COUNT(*) FROM aryx_csv_ingest_reject"):
            self._rows = [(sum(1 for x in d.rejects if x["workspace_id"] == p[0] and x["run_id"] == p[1]
                               and x["state"] == "open"),)]
        else:
            raise AssertionError("unexpected SQL: " + sql[:90])

    def executemany(self, sql, rows):
        d = self.db
        rows = list(rows)
        if sql.startswith("INSERT INTO aryx_csv_ingest_reject"):
            for run_id, ws, line, code, reason, row_json in rows:
                d.rejects.append({"reject_id": len(d.rejects) + 1, "run_id": run_id, "workspace_id": ws, "line_no": line,
                                  "reason_code": code, "reason": reason, "row_json": row_json, "state": "open", "attempts": 0})
            return
        if "SET state = 'resolved'" in sql:
            for ws, rid in rows:
                x = d.by_id(rid, ws); x["state"] = "resolved"; x["attempts"] += 1
            return
        if "attempts = attempts + 1, reason = %s" in sql:
            for reason, ws, rid in rows:
                x = d.by_id(rid, ws); x["state"] = "open"; x["attempts"] += 1; x["reason"] = reason
            return
        if "SET state = 'open' WHERE" in sql:
            for ws, rid in rows:
                d.by_id(rid, ws)["state"] = "open"
            return
        super().executemany(sql, rows)

    def fetchall(self):
        return self._rows


class IssueDb(FakeDb):
    def __init__(self):
        super().__init__()
        self.runs, self.rejects = {}, []

    def by_id(self, rid, ws):
        return next(x for x in self.rejects if x["reject_id"] == rid and x["workspace_id"] == ws)

    @staticmethod
    def run_tuple(r):
        return (r["run_id"], r["job_id"], r["source_file"], r["table_name"], r["status"], r["error_code"], r["message"],
                r["rows_loaded"], r["rows_bad"], r["rows_rejected"], r["rows_truncated"], r["reject_total"],
                r["reject_stored"], r["file_size"], 1 if r["file_gz_b64"] else 0, r["rerun_of"], r["state"], r["created_at"], 0,
                r.get("logical_table"))

    @contextmanager
    def __call__(self):
        db = self
        yield type("C", (), {"cursor": lambda self: IssueCursor(db)})()

    def open_count(self, run_id):
        return sum(1 for x in self.rejects if x["run_id"] == run_id and x["state"] == "open")


def widgets_table(db, name_len=10, owner="csv_bml_ingestion:ws=3"):
    db.catalog["WIDGETS"] = [("NAME", "VARCHAR2", name_len, name_len, "B", None, None),
                             ("QTY", "NUMBER", 22, None, None, 10, 0)]
    db.comments["WIDGETS"] = owner


def seeded_run(db, ws=3, rows=None, status="loaded", file_bytes=None, table="widgets"):
    """A stored run with over-length rejects, as the pipeline would have recorded it."""
    rows = rows if rows is not None else [
        RejectedRow(2, "CBI_VALUE_TOO_LONG", "name: 14 bytes > limit 10", {"columns": {"name": "a-long-name-xx", "qty": 1}}),
        RejectedRow(5, "CBI_VALUE_TOO_LONG", "name: 30 bytes > limit 10", {"columns": {"name": "x" * 30, "qty": 2}}),
        RejectedRow(7, "CBI_BAD_ROW", "expected 2 cells, got 1", {"cells": ["only-one"]}),
    ]
    res = IngestResult(source="widgets.csv", status=status, table=table, rows_loaded=10, rows_bad=1, rows_rejected=2,
                       reject_rows=rows, reject_total=len(rows))
    return IssueStore(db).record_run(ws, "job-1", res, file_bytes)


# ------------------------------------------------------------------ collecting rejected rows
def test_reader_keeps_bad_rows_with_line_numbers_and_raw_cells(tmp_path):
    p = write_csv(tmp_path / "t.csv", ["a", "n"], ["String", "Integer"], [["x", "1"], ["y", "oops"], ["short"]])
    stats = CsvStats()
    rows = list(iter_numbered_rows(p, read_layout(p), stats))
    assert [line for line, _ in rows] == [6]                    # meta block is 5 lines, so first data line is 6
    assert [(r.line_no, r.code) for r in stats.rejects.rows] == [(7, "CBI_BAD_ROW"), (8, "CBI_BAD_ROW")]
    assert stats.rejects.rows[0].payload == {"cells": ["y", "oops"]} and stats.rejects.rows[1].payload == {"cells": ["short"]}


def test_overflow_rejects_are_kept_with_column_values_for_a_rerun(bml_index, tmp_path):
    rows = [["modify", "k", "ok", "B", "", "", "a", "1", "R", "", "", "", "", "", ""],
            ["modify", "k", "x" * 1500, "B", "", "", "a", "2", "R", "", "", "", "", "", ""]]
    r = ingest_csv(_seq_csv(tmp_path, rows=rows), bml_index, FakeDb())
    assert (r.rows_rejected, r.reject_total) == (1, 1)
    rej = r.reject_rows[0]
    assert (rej.line_no, rej.code) == (7, "CBI_VALUE_TOO_LONG") and rej.payload["columns"]["cpqmodel"] == "x" * 1500


def test_collector_caps_stored_rows_but_counts_all(monkeypatch):
    monkeypatch.setenv("ARYX_CSV_BML_MAX_REJECT_ROWS", "3")
    c = RejectCollector()
    for i in range(10):
        c.add(RejectedRow(i, "CBI_BAD_ROW", "r", {"cells": []}))
    assert (len(c.rows), c.total, c.capped) == (3, 10, True)


# ------------------------------------------------------------------ the issue store
def test_should_record_only_when_something_needs_attention():
    assert not should_record(IngestResult(source="a", status="loaded", rows_loaded=5))
    assert should_record(IngestResult(source="a", status="skipped"))
    assert should_record(IngestResult(source="a", status="failed"))
    assert should_record(IngestResult(source="a", status="loaded", rows_rejected=1, reject_total=1))


def test_record_and_read_back_a_run_with_its_rejects():
    db = IssueDb()
    run_id = seeded_run(db)
    store = IssueStore(db)
    run = store.get_run(3, run_id)
    assert (run["status"], run["table_name"], run["reject_stored"], run["state"], run["file_kept"]) == ("loaded", "widgets", 3, "open", False)
    assert [r["line_no"] for r in store.list_rejects(3, run_id)] == [2, 5, 7]
    assert store.list_rejects(3, run_id)[0]["row"] == {"columns": {"name": "a-long-name-xx", "qty": 1}}
    assert [r["line_no"] for r in store.list_rejects(3, run_id, offset=1, limit=1)] == [5]


def test_file_is_kept_only_for_runs_that_did_not_load():
    db = IssueDb()
    skipped = seeded_run(db, status="skipped", file_bytes=b"a,b\n1,2\n", rows=[])
    loaded = seeded_run(db, status="loaded", file_bytes=b"a,b\n1,2\n")
    store = IssueStore(db)
    assert store.get_file(3, skipped) == ("widgets.csv", b"a,b\n1,2\n")
    assert store.get_file(3, loaded) is None and store.get_run(3, skipped)["file_kept"] is True


def test_oversized_file_is_not_kept_and_says_so(monkeypatch):
    monkeypatch.setenv("ARYX_CSV_BML_MAX_STORED_FILE_MB", "0")
    db = IssueDb()
    run_id = seeded_run(db, status="skipped", file_bytes=b"x" * 5000, rows=[])
    run = IssueStore(db).get_run(3, run_id)
    assert not run["file_kept"] and "too large to keep" in run["message"]


def test_everything_is_scoped_to_the_workspace():
    db = IssueDb()
    run_id = seeded_run(db, ws=3)
    store = IssueStore(db)
    assert store.get_run(4, run_id) is None and store.list_runs(4) == [] and store.get_file(4, run_id) is None
    assert [r["run_id"] for r in store.list_runs(3)] == [run_id] and store.list_runs(3, job_id="other") == []


# ------------------------------------------------------------------ re-running rejected rows
def test_rerun_inserts_rows_that_now_fit_and_resolves_them():
    db = IssueDb()
    widgets_table(db, name_len=40)                             # admin widened the column
    run_id = seeded_run(db)
    out = rerun_rejects(db, 3, run_id)
    assert (out["attempted"], out["inserted"], out["still_rejected"], out["not_rerunnable"]) == (3, 2, 0, 1)
    ins = [e for e in db.log if e[0] == "executemany" and e[1].startswith("INSERT INTO widgets")][0]
    assert ins[1] == "INSERT INTO widgets (name, qty) VALUES (%s, %s)" and ins[2] == [("a-long-name-xx", 1), ("x" * 30, 2)]
    assert [x["state"] for x in db.rejects] == ["resolved", "resolved", "open"]      # malformed row stays open
    assert out["run_state"] == "open" and db.open_count(run_id) == 1


def test_rerun_leaves_rows_that_still_do_not_fit_open_with_attempts_counted():
    db = IssueDb()
    widgets_table(db, name_len=20)                             # fits the 14-byte one, not the 30-byte one
    run_id = seeded_run(db)
    out = rerun_rejects(db, 3, run_id)
    assert (out["inserted"], out["still_rejected"]) == (1, 1)
    states = {x["line_no"]: (x["state"], x["attempts"]) for x in db.rejects}
    assert states == {2: ("resolved", 1), 5: ("open", 1), 7: ("open", 0)}
    assert "30 bytes" in db.rejects[1]["reason"]


def test_rerun_with_truncate_policy_inserts_cut_values():
    db = IssueDb()
    widgets_table(db, name_len=20)
    run_id = seeded_run(db, rows=[RejectedRow(5, "CBI_VALUE_TOO_LONG", "r", {"columns": {"name": "x" * 30, "qty": 2}})])
    out = rerun_rejects(db, 3, run_id, OverflowPolicy.TRUNCATE)
    assert (out["inserted"], out["truncated"], out["run_state"]) == (1, 1, "resolved")
    assert [e for e in db.log if e[0] == "executemany" and e[1].startswith("INSERT INTO widgets")][0][2] == [("x" * 20, 2)]


def test_a_second_rerun_finds_nothing_left_to_insert():
    db = IssueDb()
    widgets_table(db, name_len=40)
    run_id = seeded_run(db, rows=[RejectedRow(2, "CBI_VALUE_TOO_LONG", "r", {"columns": {"name": "abcdefghijklmnop", "qty": 1}})])
    assert rerun_rejects(db, 3, run_id)["inserted"] == 1
    again = rerun_rejects(db, 3, run_id)
    assert (again["attempted"], again["inserted"]) == (0, 0)
    assert len([e for e in db.log if e[0] == "executemany" and e[1].startswith("INSERT INTO widgets")]) == 1


@pytest.mark.parametrize("kwargs,match", [
    ({"run_id": "nope"}, "run not found"),
    ({"ws": 4}, "run not found"),                                   # another workspace's run
    ({"policy": OverflowPolicy.FAIL}, "makes no sense"),
])
def test_rerun_refusals(kwargs, match):
    db = IssueDb()
    widgets_table(db, name_len=40)
    run_id = seeded_run(db)
    with pytest.raises(RerunError, match=match):
        rerun_rejects(db, kwargs.get("ws", 3), kwargs.get("run_id", run_id), kwargs.get("policy", OverflowPolicy.REJECT))


def test_rerun_refuses_a_missing_table_and_a_table_owned_by_someone_else():
    db = IssueDb()
    run_id = seeded_run(db)                                        # no widgets table in the catalog
    with pytest.raises(RerunError, match="no longer exists"):
        rerun_rejects(db, 3, run_id)
    widgets_table(db, name_len=40, owner="csv_bml_ingestion:ws=9")
    with pytest.raises(TableProtectedError):
        rerun_rejects(db, 3, run_id)
    assert all(x["state"] == "open" for x in db.rejects)           # nothing was claimed or changed


def test_rerun_never_uses_columns_that_are_not_in_the_table():
    db = IssueDb()
    widgets_table(db, name_len=40)
    run_id = seeded_run(db, rows=[RejectedRow(2, "CBI_VALUE_TOO_LONG", "r", {"columns": {"name": "a", "qty": 1, "evil; drop": 2}})])
    out = rerun_rejects(db, 3, run_id)
    assert (out["inserted"], out["not_rerunnable"]) == (0, 1)
    assert not [e for e in db.log if e[0] == "executemany" and e[1].startswith("INSERT INTO widgets")]


# ------------------------------------------------------------------ upload session records issues
def _session(monkeypatch, bml_index, db, tmp_path):
    from aryx.csv_bml_ingestion import db as dbmod, llm_client, stored_graph, upload_hook as uh
    monkeypatch.setattr(dbmod, "oracle_connection_factory", lambda: db)
    monkeypatch.setattr(stored_graph, "StoredGraphLookup", lambda factory, ws: bml_index)
    monkeypatch.setattr(llm_client, "project_llm_completer", lambda: None)
    monkeypatch.setenv("ARYX_CSV_BML_SQL_DIR", str(tmp_path / "sqlroot"))
    return uh.CsvBmlUploadSession(3, "job-9")


def test_session_stores_rejected_rows_and_a_clean_run_is_not_stored(monkeypatch, bml_index, tmp_path):
    import shutil
    from .conftest import FIXTURE_SQL
    db = IssueDb()
    shutil.copytree(FIXTURE_SQL, tmp_path / "sqlroot" / "ws_3")
    sess = _session(monkeypatch, bml_index, db, tmp_path)
    clean = write_csv(tmp_path / "c.csv", SEQ_HEADER, ["String"] * 15,
                      [["modify", "k", "M", "B", "", "", "a", "1", "R", "", "", "", "", "", ""]]).read_bytes()
    assert sess.ingest(clean, "attrSequence.csv").run_id == "" and db.runs == {}
    dirty = write_csv(tmp_path / "d.csv", SEQ_HEADER, ["String"] * 15,
                      [["modify", "k", "M", "B", "", "", "a", "1", "R", "", "", "", "", "", ""],
                       ["modify", "k", "x" * 1500, "B", "", "", "a", "2", "R", "", "", "", "", "", ""],
                       ["short"]]).read_bytes()
    r = sess.ingest(dirty, "attrSequence.csv")
    assert r.status == "loaded" and r.run_id
    run = IssueStore(db).get_run(3, r.run_id)
    assert (run["job_id"], run["rows_loaded"], run["reject_stored"], run["file_kept"]) == ("job-9", 1, 2, False)
    assert sorted(x["reason_code"] for x in IssueStore(db).list_rejects(3, r.run_id)) == ["CBI_BAD_ROW", "CBI_VALUE_TOO_LONG"]


def test_session_stores_a_skipped_file_with_the_file_for_rerun(monkeypatch, bml_index, tmp_path):
    db = IssueDb()
    sess = _session(monkeypatch, bml_index, db, tmp_path)
    body = write_csv(tmp_path / "x.csv", ["a"], ["String"], [["1"]]).read_bytes()
    r = sess.ingest(body, "ar1Matrix.csv")                         # no query reads this table
    assert (r.status, r.error_code) == ("skipped", "CBI_BML_NOT_FOUND") and r.run_id
    assert IssueStore(db).get_file(3, r.run_id) == ("ar1Matrix.csv", body)


def test_a_storage_failure_never_fails_the_upload(monkeypatch, bml_index, tmp_path):
    db = IssueDb()
    sess = _session(monkeypatch, bml_index, db, tmp_path)
    monkeypatch.setattr(st.IssueStore, "record_run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    r = sess.ingest(write_csv(tmp_path / "x.csv", ["a"], ["String"], [["1"]]).read_bytes(), "ar1Matrix.csv")
    assert (r.status, r.run_id) == ("skipped", "")


# ------------------------------------------------------------------ the API
@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from aryx.api import csv_bml_api as api
    db = IssueDb()
    monkeypatch.setattr(api, "_factory", lambda: db)
    app = FastAPI()
    app.include_router(api.csv_bml_router())
    from aryx.api.security import require_api_key
    app.dependency_overrides[require_api_key] = lambda: "test-key"
    c = TestClient(app)
    c.db, c.api, c.app = db, api, app
    return c


def test_api_lists_gets_and_pages_runs_scoped_to_the_workspace(client):
    run_id = seeded_run(client.db, ws=3)
    runs = client.get("/admin/csv-bml/runs", params={"workspace_id": 3}).json()
    assert [r["run_id"] for r in runs] == [run_id] and runs[0]["table_name"] == "widgets"
    assert client.get("/admin/csv-bml/runs", params={"workspace_id": 4}).json() == []
    assert client.get(f"/admin/csv-bml/runs/{run_id}", params={"workspace_id": 3}).json()["reject_stored"] == 3
    assert client.get(f"/admin/csv-bml/runs/{run_id}", params={"workspace_id": 4}).status_code == 404
    rej = client.get(f"/admin/csv-bml/runs/{run_id}/rejects", params={"workspace_id": 3, "limit": 2}).json()
    assert [r["line_no"] for r in rej] == [2, 5]
    assert client.get(f"/admin/csv-bml/runs/{run_id}/rejects", params={"workspace_id": 4}).status_code == 404


def test_api_downloads_rejects_as_csv(client):
    run_id = seeded_run(client.db, ws=3, rows=[
        RejectedRow(2, "CBI_VALUE_TOO_LONG", "name too long", {"columns": {"name": "abc", "qty": 1}}),
        RejectedRow(5, "CBI_VALUE_TOO_LONG", "name too long", {"columns": {"name": "def", "qty": None}})])
    r = client.get(f"/admin/csv-bml/runs/{run_id}/rejects.csv", params={"workspace_id": 3})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert r.text.splitlines()[:3] == ["line_no,reason_code,reason,name,qty", "2,CBI_VALUE_TOO_LONG,name too long,abc,1",
                                       "5,CBI_VALUE_TOO_LONG,name too long,def,"]


def test_api_rerun_rows(client):
    widgets_table(client.db, name_len=40)
    run_id = seeded_run(client.db, ws=3)
    ok = client.post(f"/admin/csv-bml/runs/{run_id}/rerun-rows", params={"workspace_id": 3})
    assert ok.status_code == 200 and ok.json()["inserted"] == 2 and ok.json()["not_rerunnable"] == 1
    assert client.post(f"/admin/csv-bml/runs/{run_id}/rerun-rows", params={"workspace_id": 4}).status_code == 404
    assert client.post(f"/admin/csv-bml/runs/{run_id}/rerun-rows", params={"workspace_id": 3, "policy": "fail"}).status_code == 400
    client.db.comments["WIDGETS"] = "someone-else"
    refused = client.post(f"/admin/csv-bml/runs/{run_id}/rerun-rows", params={"workspace_id": 3})
    assert refused.status_code == 409 and "CBI_TABLE_PROTECTED" in refused.json()["detail"]


def _rerun_file_setup(client, monkeypatch, enabled=True, backend="local"):
    api = client.api
    monkeypatch.setenv("ARYX_CSV_BML_ENABLED", "true" if enabled else "")
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(effective_worker_backend=lambda: backend,
                                                                      effective_dsn=lambda: "dsn"))
    submitted, created = [], []

    class Fut:
        def add_done_callback(self, fn): pass

    class Jobs:
        def __init__(self, dsn): pass
        def create(self, job_id, system, dataset, ws): created.append((job_id, dataset, ws))
        def close(self): pass
    monkeypatch.setattr("aryx.store.job_store.JobStore", Jobs)
    monkeypatch.setattr("aryx.api.file_ingest.file_ingest_api._get_executor",
                        lambda: SimpleNamespace(submit=lambda *a: (submitted.append(a), Fut())[1]))
    return submitted, created


def test_api_rerun_file_resubmits_the_stored_file_through_the_upload_job(client, monkeypatch):
    submitted, created = _rerun_file_setup(client, monkeypatch)
    run_id = seeded_run(client.db, ws=3, status="skipped", file_bytes=b"a,b\n1,2\n", rows=[])
    r = client.post(f"/admin/csv-bml/runs/{run_id}/rerun-file", params={"workspace_id": 3})
    assert r.status_code == 200 and r.json()["status"] == "queued" and r.json()["file"] == "widgets.csv"
    fn, items, _ot, _mk, _fk, job_id, ws, _ = submitted[0]
    assert items == [(b"a,b\n1,2\n", "widgets.csv")] and ws == 3 and job_id == r.json()["job_id"]
    assert created == [(job_id, "re-run widgets.csv", 3)]
    assert client.db.runs[run_id]["state"] == "superseded"                    # replaced by the new job's run


@pytest.mark.parametrize("setup,status,why", [
    ({"enabled": False}, 409, "ARYX_CSV_BML_ENABLED"),
    ({"backend": "oci_functions"}, 409, "local worker"),
])
def test_api_rerun_file_refusals_by_configuration(client, monkeypatch, setup, status, why):
    _rerun_file_setup(client, monkeypatch, **setup)
    run_id = seeded_run(client.db, ws=3, status="skipped", file_bytes=b"x", rows=[])
    r = client.post(f"/admin/csv-bml/runs/{run_id}/rerun-file", params={"workspace_id": 3})
    assert r.status_code == status and why in r.json()["detail"]


def test_api_rerun_file_refusals_by_run(client, monkeypatch):
    _rerun_file_setup(client, monkeypatch)
    loaded = seeded_run(client.db, ws=3, status="loaded", file_bytes=b"x")
    no_file = seeded_run(client.db, ws=3, status="failed", file_bytes=None, rows=[])
    other_ws = seeded_run(client.db, ws=5, status="skipped", file_bytes=b"x", rows=[])
    post = lambda rid: client.post(f"/admin/csv-bml/runs/{rid}/rerun-file", params={"workspace_id": 3})
    assert post(loaded).status_code == 409 and "rerun-rows" in post(loaded).json()["detail"]
    assert post(no_file).status_code == 409 and "upload it again" in post(no_file).json()["detail"]
    assert post(other_ws).status_code == 404 and post("nope").status_code == 404


def test_api_returns_501_without_the_oracle_backend(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from aryx.api import csv_bml_api as api
    from aryx.csv_bml_ingestion import db as dbmod
    from aryx.csv_bml_ingestion.errors import DatabaseUnavailableError

    def boom():
        raise DatabaseUnavailableError("not oci")
    monkeypatch.setattr(dbmod, "oracle_connection_factory", boom)
    app = FastAPI()
    app.include_router(api.csv_bml_router())
    from aryx.api.security import require_api_key
    app.dependency_overrides[require_api_key] = lambda: "k"
    assert TestClient(app).get("/admin/csv-bml/runs", params={"workspace_id": 1}).status_code == 501


# ------------------------------------------------------------------ review fixes
def test_every_route_needs_the_api_key_and_an_explicit_workspace(client):
    client.app.dependency_overrides.clear()                      # the real guard is back
    assert client.get("/admin/csv-bml/runs", params={"workspace_id": 3}).status_code == 401
    assert client.post("/admin/csv-bml/runs/x/rerun-rows", params={"workspace_id": 3}).status_code == 401
    from aryx.api.security import require_api_key
    client.app.dependency_overrides[require_api_key] = lambda: "k"
    assert client.get("/admin/csv-bml/runs").status_code == 422   # workspace_id has no silent default


def test_rejects_csv_is_formula_safe(client):
    run_id = seeded_run(client.db, ws=3, rows=[
        RejectedRow(2, "CBI_VALUE_TOO_LONG", "=HYPERLINK(\"http://x\")", {"columns": {"name": "=cmd|' /C calc'!A0", "qty": "@sum"}}),
        RejectedRow(3, "CBI_VALUE_TOO_LONG", "r", {"columns": {"name": "-2+3", "qty": 5}})])
    body = client.get(f"/admin/csv-bml/runs/{run_id}/rejects.csv", params={"workspace_id": 3}).text
    assert "'=cmd|" in body and "'@sum" in body and "'-2+3" in body and "'=HYPERLINK" in body
    assert not any(line.split(",")[3:4] and line.split(",")[3].startswith(("=", "+", "-", "@")) for line in body.splitlines()[1:])


def test_rerun_file_twice_only_queues_one_job_and_the_second_click_is_refused(client, monkeypatch):
    submitted, created = _rerun_file_setup(client, monkeypatch)
    run_id = seeded_run(client.db, ws=3, status="skipped", file_bytes=b"a,b\n1,2\n", rows=[])
    first = client.post(f"/admin/csv-bml/runs/{run_id}/rerun-file", params={"workspace_id": 3})
    second = client.post(f"/admin/csv-bml/runs/{run_id}/rerun-file", params={"workspace_id": 3})
    assert (first.status_code, second.status_code) == (200, 409) and len(submitted) == 1 and len(created) == 1
    assert "already" in second.json()["detail"]


def test_rerun_file_gives_the_run_back_when_the_job_cannot_be_queued(client, monkeypatch):
    _rerun_file_setup(client, monkeypatch)
    monkeypatch.setattr("aryx.api.file_ingest.file_ingest_api._get_executor",
                        lambda: (_ for _ in ()).throw(RuntimeError("executor down")))
    run_id = seeded_run(client.db, ws=3, status="skipped", file_bytes=b"x", rows=[])
    r = client.post(f"/admin/csv-bml/runs/{run_id}/rerun-file", params={"workspace_id": 3})
    assert r.status_code == 503 and client.db.runs[run_id]["state"] == "open"      # issue stays actionable


def test_rerun_of_a_run_that_is_not_open_is_refused(client, monkeypatch):
    _rerun_file_setup(client, monkeypatch)
    run_id = seeded_run(client.db, ws=3, status="skipped", file_bytes=b"x", rows=[])
    client.db.runs[run_id]["state"] = "resolved"
    r = client.post(f"/admin/csv-bml/runs/{run_id}/rerun-file", params={"workspace_id": 3})
    assert r.status_code == 409 and "already resolved" in r.json()["detail"]


def test_rerun_rows_refuses_a_superseded_run_and_never_resurrects_its_state():
    db = IssueDb()
    widgets_table(db, name_len=40)
    run_id = seeded_run(db)
    IssueStore(db).set_run_state(3, run_id, "superseded")
    with pytest.raises(RerunError, match="superseded"):
        rerun_rejects(db, 3, run_id)
    with db() as conn:                                                # the state guard itself
        IssueStore.finish_run_if_clean(conn.cursor(), 3, run_id)
    assert db.runs[run_id]["state"] == "superseded"


def test_a_database_error_during_rerun_is_reported_not_a_500(client, monkeypatch):
    widgets_table(client.db, name_len=40)
    run_id = seeded_run(client.db, ws=3)
    monkeypatch.setattr(client.api, "rerun_rejects", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ORA-01400")))
    r = client.post(f"/admin/csv-bml/runs/{run_id}/rerun-rows", params={"workspace_id": 3})
    assert r.status_code == 409 and "nothing was changed" in r.json()["detail"] and "ORA-01400" not in r.json()["detail"]


def test_a_newer_upload_of_the_same_file_supersedes_stale_issues(monkeypatch, bml_index, tmp_path):
    import shutil
    from .conftest import FIXTURE_SQL
    db = IssueDb()
    shutil.copytree(FIXTURE_SQL, tmp_path / "sqlroot" / "ws_3")
    sess = _session(monkeypatch, bml_index, db, tmp_path)
    dirty = write_csv(tmp_path / "d.csv", SEQ_HEADER, ["String"] * 15,
                      [["modify", "k", "x" * 1500, "B", "", "", "a", "2", "R", "", "", "", "", "", ""]]).read_bytes()
    clean = write_csv(tmp_path / "c.csv", SEQ_HEADER, ["String"] * 15,
                      [["modify", "k", "M", "B", "", "", "a", "1", "R", "", "", "", "", "", ""]]).read_bytes()
    first = sess.ingest(dirty, "attrSequence.csv").run_id
    other = sess.ingest(dirty, "other_file.csv")                  # a different file: untouched below
    assert db.runs[first]["state"] == "open"
    sess.ingest(clean, "attrSequence.csv")                        # re-upload loads cleanly: first run is stale
    assert db.runs[first]["state"] == "superseded"
    second = sess.ingest(dirty, "attrSequence.csv").run_id        # re-upload with rejects: new run replaces it
    third = sess.ingest(dirty, "attrSequence.csv").run_id
    assert db.runs[second]["state"] == "superseded" and db.runs[third]["state"] == "open"


def test_purge_issues_removes_a_workspace_and_cascades(monkeypatch):
    db = IssueDb()
    mine, other = seeded_run(db, ws=3), seeded_run(db, ws=4)
    st.purge_issues(db, 3)
    assert list(db.runs) == [other] and all(x["run_id"] == other for x in db.rejects)
    st.purge_issues(db, None)
    assert db.runs == {} and db.rejects == []


def test_workspace_cleanup_can_never_break_a_workspace_delete(monkeypatch):
    from aryx.store.oracle_workspace import OracleWorkspaceStore
    store = OracleWorkspaceStore.__new__(OracleWorkspaceStore)
    store._pool = SimpleNamespace(connection=lambda: (_ for _ in ()).throw(RuntimeError("ORA-00942: table does not exist")))
    store._purge_csv_issues(7)                                     # must swallow (and log), not raise


def test_a_failed_or_skipped_reupload_does_not_supersede_a_run_whose_table_is_still_valid(monkeypatch, bml_index, tmp_path):
    import shutil
    from .conftest import FIXTURE_SQL
    db = IssueDb()
    shutil.copytree(FIXTURE_SQL, tmp_path / "sqlroot" / "ws_3")
    sess = _session(monkeypatch, bml_index, db, tmp_path)
    dirty = write_csv(tmp_path / "d.csv", SEQ_HEADER, ["String"] * 15,
                      [["modify", "k", "x" * 1500, "B", "", "", "a", "2", "R", "", "", "", "", "", ""]]).read_bytes()
    partial = sess.ingest(dirty, "attrSequence.csv").run_id               # loaded with a reject: A is open
    # the same file again, but the graph lookup now finds nothing -> skipped, the table is NOT touched
    monkeypatch.setattr(sess, "_lookup", SimpleNamespace(lookup=lambda t: SimpleNamespace(
        matches=(), near_misses=(), table=t), script_count=0))
    skipped = sess.ingest(dirty, "attrSequence.csv")
    assert skipped.status == "skipped" and skipped.run_id
    assert db.runs[partial]["state"] == "open"                              # still actionable against the table
    again = sess.ingest(dirty, "attrSequence.csv")                          # a second skipped attempt replaces the first
    assert db.runs[skipped.run_id]["state"] == "superseded" and db.runs[again.run_id]["state"] == "open"


def test_a_reupload_for_a_different_table_does_not_supersede(monkeypatch):
    db = IssueDb()
    old = seeded_run(db, ws=3, table="widgets")
    IssueStore(db).supersede_older(3, "widgets.csv", "gadgets", "new-run", reloaded=True)
    assert db.runs[old]["state"] == "open"
    IssueStore(db).supersede_older(3, "widgets.csv", "widgets", "new-run", reloaded=True)
    assert db.runs[old]["state"] == "superseded"


def test_a_run_superseded_during_a_rerun_cannot_be_claimed():
    db = IssueDb()
    widgets_table(db, name_len=40)
    run_id = seeded_run(db)
    with db() as conn:
        IssueStore(db).set_run_state(3, run_id, "superseded")               # the newer upload won the race
        assert IssueStore.claim_open(conn.cursor(), 3, run_id) == []
    assert all(x["state"] == "open" for x in db.rejects)


def test_a_failing_revert_after_a_queueing_error_still_answers_503(client, monkeypatch):
    _rerun_file_setup(client, monkeypatch)
    monkeypatch.setattr("aryx.api.file_ingest.file_ingest_api._get_executor",
                        lambda: (_ for _ in ()).throw(RuntimeError("executor down")))
    monkeypatch.setattr(st.IssueStore, "set_run_state", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    run_id = seeded_run(client.db, ws=3, status="skipped", file_bytes=b"x", rows=[])
    assert client.post(f"/admin/csv-bml/runs/{run_id}/rerun-file", params={"workspace_id": 3}).status_code == 503


# ------------------------------------------------------------------ per-workspace table names in stored issues
def test_stored_run_keeps_the_physical_table_for_rerun_and_the_logical_name_for_display():
    db = IssueDb()
    res = IngestResult(source="widgets.csv", status="loaded", table="widgets", physical_table="ws3_widgets",
                       rows_loaded=2, rows_rejected=1, reject_total=1,
                       reject_rows=[RejectedRow(2, "CBI_VALUE_TOO_LONG", "r", {"columns": {"name": "x" * 20, "qty": 1}})])
    run_id = IssueStore(db).record_run(3, "job-1", res)
    run = IssueStore(db).get_run(3, run_id)
    assert (run["table_name"], run["logical_table"]) == ("ws3_widgets", "widgets")


def test_rerun_loads_into_the_workspaces_own_table_not_the_shared_name():
    db = IssueDb()
    db.catalog["WS3_WIDGETS"] = [("NAME", "VARCHAR2", 40, 40, "B", None, None), ("QTY", "NUMBER", 22, None, None, 10, 0)]
    db.comments["WS3_WIDGETS"] = "csv_bml_ingestion:ws=3"
    res = IngestResult(source="widgets.csv", status="loaded", table="widgets", physical_table="ws3_widgets",
                       rows_rejected=1, reject_total=1,
                       reject_rows=[RejectedRow(2, "CBI_VALUE_TOO_LONG", "r", {"columns": {"name": "x" * 20, "qty": 1}})])
    run_id = IssueStore(db).record_run(3, "job-1", res)
    out = rerun_rejects(db, 3, run_id)
    assert (out["table"], out["inserted"]) == ("ws3_widgets", 1)
    assert [e[1] for e in db.log if e[0] == "executemany" and e[1].startswith("INSERT INTO")][-1].startswith("INSERT INTO ws3_widgets ")


def test_api_returns_both_names(client):
    db = client.db
    res = IngestResult(source="widgets.csv", status="skipped", table="widgets", physical_table="ws3_widgets")
    IssueStore(db).record_run(3, "job-1", res, b"a\n1\n")
    run = client.get("/admin/csv-bml/runs", params={"workspace_id": 3}).json()[0]
    assert (run["table_name"], run["logical_table"]) == ("ws3_widgets", "widgets")
