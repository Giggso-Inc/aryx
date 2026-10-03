"""Knowledge-graph route: enrich at XML ingest, search the stored graph at CSV ingest, upload wiring."""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from aryx.cpq_ingestion.raw_graph import store as raw_store
from aryx.cpq_ingestion.raw_graph.xml_projector import project_xml_to_raw_graph
from aryx.csv_bml_ingestion import stored_graph as sg
from aryx.csv_bml_ingestion.bml_graph import QUERIES_KEY, QUERY_TABLES_KEY, TABLES_KEY, enrich_projection
from aryx.csv_bml_ingestion.config import csv_bml_enabled
from aryx.csv_bml_ingestion.stored_graph import StoredGraphLookup

from .conftest import BML_XML, FakeDb, write_csv
from .test_pipeline import SEQ_HEADER

LONG = "SELECT AttrName, Seq FROM $attrSeqTableName WHERE CPQModel=$m " + "AND x=1 " * 60   # > 200 chars
XML = ("<root><fn><id>111</id><guid>g-111</guid><name>Seq rule</name>"
       f"<script_text>attrSeqTableName = \"attrSequence\"; rs = db.q(\"{LONG}\");</script_text></fn>"
       "<fn><id>222</id><script_text>q = \"select a from attrToPDNonFrequency where b=1\" + \"\";</script_text></fn>"
       "<other><note>nothing here</note></other></root>").encode()


@pytest.fixture
def enriched():
    return enrich_projection(project_xml_to_raw_graph(XML))


# --- enrichment at XML-ingest time ------------------------------------------------------
def test_enrich_adds_short_lists_only_to_nodes_with_queries(enriched):
    tagged = {n.tag: n.properties for n in enriched.nodes if TABLES_KEY in n.properties}
    assert [n.properties[TABLES_KEY] for n in enriched.nodes if TABLES_KEY in n.properties] == [
        ["attrsequence"], ["attrtopdnonfrequency"]]
    props = tagged["script_text"]
    assert len(props[QUERIES_KEY]) == len(props[QUERY_TABLES_KEY]) == 1
    assert all(TABLES_KEY not in n.properties for n in enriched.nodes if n.tag in ("note", "id", "guid"))


def test_enrich_does_not_mutate_the_input():
    proj = project_xml_to_raw_graph(XML)
    enrich_projection(proj)
    assert all(TABLES_KEY not in n.properties for n in proj.nodes)


def test_unresolvable_variable_tables_are_not_recorded():
    proj = project_xml_to_raw_graph(b'<r><s>x = "select a from $never_assigned";</s></r>')
    assert all(TABLES_KEY not in n.properties for n in enrich_projection(proj).nodes)


def test_lists_survive_the_graph_store_clip_but_script_text_does_not():
    """The reason this design exists: the store clips strings to ~200 chars, not lists."""
    from aryx.graph.oracle_graph_store_helpers import _safe_attrs_json
    node = next(n for n in enrich_projection(project_xml_to_raw_graph(XML)).nodes if TABLES_KEY in n.properties
                and n.tag == "script_text" and "attrSeq" in n.properties["text"])
    stored = json.loads(_safe_attrs_json(node.properties))
    assert len(stored["text"]) == 201 and stored["text"].endswith("…")        # clipped: unusable for search
    assert stored[TABLES_KEY] == ["attrsequence"]                              # intact
    assert stored[QUERIES_KEY][0].count("x=1") == 60                           # full query kept


# --- XML-ingest hook in the existing raw-graph store ------------------------------------------
def _capture(monkeypatch):
    seen = {}
    monkeypatch.setattr(raw_store, "write_raw_graph",
                        lambda projection, **kw: seen.setdefault("p", projection) or SimpleNamespace())
    return seen


def test_xml_ingest_hook_is_off_by_default(monkeypatch):
    monkeypatch.delenv("ARYX_CSV_BML_ENABLED", raising=False)
    seen = _capture(monkeypatch)
    raw_store.project_and_write_raw_graph(XML, workspace_id=1, source_key="k", dsn="", graph_url="")
    assert all(TABLES_KEY not in n.properties for n in seen["p"].nodes)


def test_xml_ingest_hook_enriches_when_enabled(monkeypatch):
    monkeypatch.setenv("ARYX_CSV_BML_ENABLED", "true")
    seen = _capture(monkeypatch)
    raw_store.project_and_write_raw_graph(XML, workspace_id=1, source_key="k", dsn="", graph_url="")
    assert sum(TABLES_KEY in n.properties for n in seen["p"].nodes) == 2


def test_xml_ingest_hook_failure_keeps_the_plain_raw_graph(monkeypatch):
    monkeypatch.setenv("ARYX_CSV_BML_ENABLED", "true")
    monkeypatch.setattr("aryx.csv_bml_ingestion.bml_graph.enrich_projection",
                        lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    seen = _capture(monkeypatch)
    raw_store.project_and_write_raw_graph(XML, workspace_id=1, source_key="k", dsn="", graph_url="")
    assert len(seen["p"].nodes) > 3 and all(TABLES_KEY not in n.properties for n in seen["p"].nodes)


@pytest.mark.parametrize("val,expected", [("1", True), ("true", True), ("YES", True), ("on", True),
                                          ("", False), ("0", False), ("false", False), ("nope", False)])
def test_enable_switch(monkeypatch, val, expected):
    monkeypatch.setenv("ARYX_CSV_BML_ENABLED", val)
    assert csv_bml_enabled() is expected


# --- searching the stored graph at CSV-ingest time ----------------------------------------------
class FakeGraphDb:
    """Mimics the two graph tables and answers the exact SQL ``StoredGraphLookup`` sends."""

    def __init__(self, projection, ws_scope: int) -> None:
        self.ws = ws_scope
        self.v = {n.id: (n.tag, n.properties) for n in projection.nodes}
        self.e = [(e.source_id, e.target_id) for e in projection.edges]
        self.calls: list[tuple] = []

    @contextmanager
    def __call__(self):
        db = self

        class Cur:
            def execute(self, sql, params=None):
                db.calls.append((sql, params))
                self.sql, self.p = sql, params

            def fetchall(self):
                s, p = self.sql, self.p
                if s == sg._ENRICHED_SQL:
                    lo, hi = p
                    return [(db.ws, i, t, a) for i, (t, a) in db.v.items() if lo <= db.ws <= hi and TABLES_KEY in a]
                if s == sg._PARENT_SQL:
                    return [(src,) for src, tgt in db.e if tgt == p[1]]
                if s == sg._TYPE_SQL:
                    return [(db.v[p[1]][0],)]
                if s == sg._SIBLINGS_SQL:
                    return [(db.v[t][0], db.v[t][1]) for src, t in db.e if src == p[1] and t != p[2]]
                raise AssertionError("unexpected SQL " + s)

        yield type("C", (), {"cursor": lambda self: Cur()})()


@pytest.fixture
def lookup(enriched, monkeypatch):
    from aryx.cpq_ingestion.naming import raw_workspace_id
    scope = raw_workspace_id(3, 1_000_000_000, "some_file")          # a real derived scope inside ws 3's range
    monkeypatch.setattr(sg, "get_cpq_ingestion_settings", lambda: SimpleNamespace(cpq_raw_workspace_offset=1_000_000_000))
    db = FakeGraphDb(enriched, scope)
    lk = StoredGraphLookup(db, 3)
    lk.db = db
    return lk


def test_lookup_finds_scripts_from_the_graph_alone(lookup):
    for name in ("attrSequence", "ATTRSEQUENCE"):
        r = lookup.lookup(name)
        assert len(r.matches) == 1
        m = r.matches[0]
        assert (m.node_tag, m.identity, m.label) == ("script_text", {"id": "111", "guid": "g-111", "name": "Seq rule"}, "id=111")
        assert m.path[-1] == "fn" and m.queries[0].sql.startswith("SELECT AttrName, Seq FROM $attrSeqTableName")
    assert lookup.lookup("attrToPDNonFrequency").matches[0].label == "id=222"
    assert lookup.script_count == 2 and lookup.tables == ["attrsequence", "attrtopdnonfrequency"]


def test_lookup_not_found_and_near_miss(lookup):
    assert lookup.lookup("ar1Matrix").matches == ()
    assert lookup.lookup("attrtopd").near_misses == ("attrtopdnonfrequency",)


def test_lookup_searches_only_this_workspaces_id_range_with_one_scan(lookup):
    lookup.lookup("attrsequence"); lookup.lookup("attrtopdnonfrequency")
    scans = [c for c in lookup.db.calls if c[0] == sg._ENRICHED_SQL]
    assert len(scans) == 1                                            # cached across lookups
    lo, hi = scans[0][1]
    assert lo < lookup.db.ws <= hi and hi - lo == 999_999             # exactly workspace 3's range


def test_pipeline_ingests_a_csv_using_only_the_stored_graph(lookup, tmp_path, seeded_sql_root):
    csv_path = write_csv(tmp_path / "attrSequence.csv", SEQ_HEADER, ["String"] * 15,
                         [["modify", "k", "M", "B", "", "", "a", "1", "R", "", "", "", "", "", ""]])
    from aryx.csv_bml_ingestion import ingest_csv
    r = ingest_csv(csv_path, lookup, FakeDb())
    assert (r.status, r.rows_loaded, r.bml_scripts) == ("loaded", 1, ["id=111"])
    r2 = ingest_csv(write_csv(tmp_path / "ar1Matrix.csv", ["a"], ["String"], [["1"]]), lookup, FakeDb())
    assert (r2.status, r2.error_code) == ("skipped", "CBI_BML_NOT_FOUND")


# --- upload entry point ----------------------------------------------------------------------
def _session(monkeypatch, bml_index, tmp_path, db=None):
    from aryx.csv_bml_ingestion import upload_hook as uh
    from aryx.csv_bml_ingestion import db as dbmod, llm_client, stored_graph
    db = db or FakeDb()
    built = []
    monkeypatch.setattr(dbmod, "oracle_connection_factory", lambda: (built.append("factory"), db)[1])
    monkeypatch.setattr(stored_graph, "CuratedFirstLookup", lambda factory, ws: (built.append(("lookup", ws)), bml_index)[1])
    monkeypatch.setattr(llm_client, "project_llm_completer", lambda: None)
    monkeypatch.setenv("ARYX_CSV_BML_SQL_DIR", str(tmp_path / "sqlroot"))
    monkeypatch.delenv("ARYX_CSV_BML_REJECTS_DIR", raising=False)
    return uh.CsvBmlUploadSession(3), db, built


def _seq_body(tmp_path):
    return write_csv(tmp_path / "src.csv", SEQ_HEADER, ["String"] * 15,
                     [["modify", "k", "M", "B", "", "", "a", "1", "R", "", "", "", "", "", ""]]).read_bytes()


def test_session_ingests_bytes_isolates_by_workspace_and_builds_lookup_once(monkeypatch, bml_index, tmp_path):
    import shutil
    from .conftest import FIXTURE_SQL
    sess, db, built = _session(monkeypatch, bml_index, tmp_path)
    shutil.copytree(FIXTURE_SQL, tmp_path / "sqlroot" / "ws_3")          # SQL is per workspace: ws_3 only
    body = _seq_body(tmp_path)
    r1 = sess.ingest(body, "../../AttrSequence.csv")                      # path parts are stripped
    r2 = sess.ingest(body, "attrSequence.csv")
    assert (r1.status, r1.table, r1.rows_loaded) == ("loaded", "attrsequence", 1) and r2.status == "loaded"
    assert r1.physical_table == "ws3_attrsequence"                        # logical name for step 2, own table in Oracle
    assert built == ["factory", ("lookup", 3)]                            # built once for the whole job
    assert db.comments["WS3_ATTRSEQUENCE"] == "csv_bml_ingestion:ws=3"   # owned by this workspace
    assert "ATTRSEQUENCE" not in db.catalog                               # the shared logical name is never created


def test_same_csv_in_two_workspaces_lands_in_two_separate_tables(monkeypatch, bml_index, tmp_path):
    import shutil
    from .conftest import FIXTURE_SQL
    sess3, db, _ = _session(monkeypatch, bml_index, tmp_path)
    shutil.copytree(FIXTURE_SQL, tmp_path / "sqlroot" / "ws_3")
    shutil.copytree(FIXTURE_SQL, tmp_path / "sqlroot" / "ws_4")
    assert sess3.ingest(_seq_body(tmp_path), "attrSequence.csv").status == "loaded"
    from aryx.csv_bml_ingestion import upload_hook as uh
    sess4 = uh.CsvBmlUploadSession(4)
    sess4._factory, sess4._lookup = db, bml_index                          # same database, other workspace
    r = sess4.ingest(_seq_body(tmp_path), "attrSequence.csv")
    assert (r.status, r.physical_table) == ("loaded", "ws4_attrsequence")
    assert db.comments == {"WS3_ATTRSEQUENCE": "csv_bml_ingestion:ws=3", "WS4_ATTRSEQUENCE": "csv_bml_ingestion:ws=4"}
    deletes = [e[1] for e in db.log if e[0] == "execute" and e[1].startswith("DELETE")]
    assert deletes == ["DELETE FROM ws3_attrsequence", "DELETE FROM ws4_attrsequence"]   # each load touches only its own table
    inserts = [e[1].split(" ")[2] for e in db.log if e[0] == "executemany" and e[1].startswith("INSERT")]
    assert inserts == ["ws3_attrsequence", "ws4_attrsequence"]


def test_a_workspace_table_owned_by_someone_else_is_still_refused(monkeypatch, bml_index, tmp_path):
    import shutil
    from .conftest import FIXTURE_SQL
    sess, db, _ = _session(monkeypatch, bml_index, tmp_path)
    shutil.copytree(FIXTURE_SQL, tmp_path / "sqlroot" / "ws_3")
    db.catalog["WS3_ATTRSEQUENCE"] = []                                    # pre-existing, not ours
    r = sess.ingest(_seq_body(tmp_path), "attrSequence.csv")
    assert (r.status, r.error_code) == ("failed", "CBI_TABLE_PROTECTED")
    assert [e for e in db.writes() if "aryx_csv_ingest" not in e[1]] == []      # only the run bookkeeping was written


def test_session_never_raises_even_for_hostile_filenames(monkeypatch, bml_index, tmp_path):
    sess, _db, _ = _session(monkeypatch, bml_index, tmp_path)
    r = sess.ingest(b"a", "evil\x00name.csv")                              # NUL byte: write_bytes would raise
    assert r.status == "failed" and r.error_code in ("CBI_UNEXPECTED", "CBI_TABLE_NAME_INVALID", "CBI_BML_NOT_FOUND")


def test_session_reports_missing_oracle_backend(monkeypatch):
    from aryx.csv_bml_ingestion import db as dbmod, upload_hook as uh
    from aryx.csv_bml_ingestion.errors import DatabaseUnavailableError

    def boom():
        raise DatabaseUnavailableError("not oci")
    monkeypatch.setattr(dbmod, "oracle_connection_factory", boom)
    r = uh.CsvBmlUploadSession(1).ingest(b"x", "t.csv")
    assert (r.status, r.error_code) == ("failed", "CBI_DB_UNAVAILABLE")


def test_importing_config_does_not_import_the_pipeline():
    import subprocess, sys
    out = subprocess.run([sys.executable, "-c",
                          "import sys, aryx.csv_bml_ingestion.config; "
                          "print('aryx.csv_bml_ingestion.pipeline' in sys.modules)"],
                         capture_output=True, text=True, env={**__import__("os").environ, "PYTHONPATH": "src"})
    assert out.stdout.strip() == "False", out.stderr


# --- the upload loop (existing file_ingest_run) ----------------------------------------------------
class FakeJobs:
    instances: list = []

    def __init__(self, dsn):
        self.stages, self.final = [], None
        FakeJobs.instances.append(self)

    def update_stage(self, job_id, stage, pct, detail):
        self.stages.append(detail)

    def finish(self, job_id, run_id, status, error=None):
        self.final = (status, error)

    def get(self, job_id):
        return {"status": "running"}

    def close(self):
        pass


def _run_upload(monkeypatch, result_status):
    from aryx.api.file_ingest import file_ingest_run as fr
    FakeJobs.instances.clear()
    monkeypatch.setenv("ARYX_CSV_BML_ENABLED", "true")
    monkeypatch.setattr(fr, "get_settings", lambda: SimpleNamespace(effective_dsn=lambda: "dsn", csv_chunk_rows=0))
    monkeypatch.setattr(fr, "JobStore", FakeJobs)
    monkeypatch.setattr(fr, "DatasourceStore", lambda dsn: SimpleNamespace(ensure=lambda *a, **k: None))
    monkeypatch.setattr(fr, "_local_broker", lambda: None)
    calls = []

    class FakeSession:
        instances = 0

        def __init__(self, workspace_id, job_id=None):
            FakeSession.instances += 1
            self.ws = workspace_id

        def ingest(self, data, name):
            calls.append((name, self.ws))
            from aryx.csv_bml_ingestion.options import IngestResult
            return IngestResult(source=name, status=result_status, rows_loaded=5 if result_status == "loaded" else 0,
                                error_code="" if result_status == "loaded" else "CBI_BML_NOT_FOUND", message="m")
    monkeypatch.setattr("aryx.csv_bml_ingestion.upload_hook.CsvBmlUploadSession", FakeSession)
    fr._run_files([(b"a,b\n1,2\n", "attrSequence.csv")], "T", [], [], "job1", workspace_id=7)
    return calls, FakeJobs.instances[0]


def test_upload_loop_routes_csv_to_the_pipeline_and_completes(monkeypatch):
    calls, jobs = _run_upload(monkeypatch, "loaded")
    assert calls == [("attrSequence.csv", 7)] and jobs.final == ("complete", None)


def test_upload_loop_fails_the_job_when_a_csv_is_skipped(monkeypatch):
    calls, jobs = _run_upload(monkeypatch, "skipped")
    assert jobs.final[0] == "failed" and "CBI_BML_NOT_FOUND" in jobs.final[1] and "attrSequence.csv" in jobs.final[1]


def test_upload_loop_unchanged_when_switch_is_off(monkeypatch):
    from aryx.api.file_ingest import file_ingest_run as fr
    monkeypatch.delenv("ARYX_CSV_BML_ENABLED", raising=False)
    called = []
    monkeypatch.setattr("aryx.csv_bml_ingestion.upload_hook.CsvBmlUploadSession", lambda *a, **k: called.append(1))
    monkeypatch.setattr(fr, "get_settings", lambda: SimpleNamespace(effective_dsn=lambda: "d", csv_chunk_rows=0, ingest_relate=False, graph_url="g"))
    monkeypatch.setattr(fr, "JobStore", FakeJobs)
    monkeypatch.setattr(fr, "DatasourceStore", lambda dsn: SimpleNamespace(ensure=lambda *a, **k: None))
    monkeypatch.setattr(fr, "_local_broker", lambda: None)
    monkeypatch.setattr(fr, "run_pipeline", lambda **kw: called.append("legacy"))
    monkeypatch.setattr(fr, "restore_generic_source_entry", lambda *a, **k: None)
    fr._run_files([(b"a,b\n1,2\n", "x.csv")], "T", [], [], "job2", workspace_id=1)
    assert called == ["legacy"]                                       # the old CSV path, untouched


def test_upload_loop_processes_xml_before_csv_when_enabled(monkeypatch):
    """A CSV listed before its XML in the same upload must still find the XML's graph."""
    from aryx.api.file_ingest import file_ingest_run as fr
    order = []
    monkeypatch.setenv("ARYX_CSV_BML_ENABLED", "true")
    monkeypatch.setattr(fr, "get_settings", lambda: SimpleNamespace(effective_dsn=lambda: "d", csv_chunk_rows=0, graph_url="g"))
    monkeypatch.setattr(fr, "JobStore", FakeJobs)
    monkeypatch.setattr(fr, "DatasourceStore", lambda dsn: SimpleNamespace(ensure=lambda *a, **k: None))
    monkeypatch.setattr(fr, "_local_broker", lambda: None)
    monkeypatch.setattr(fr, "cpq_ingestion_pipeline_active", lambda name: False)
    monkeypatch.setattr(fr, "_xml_to_csvs", lambda data, stem, **k: (order.append("xml"), [])[1])
    monkeypatch.setattr(fr, "_detect_fk_links", lambda plans: [])
    monkeypatch.setattr(fr, "upsert_xml_catalog_entry", lambda *a, **k: None)
    monkeypatch.setattr(fr, "xml_asset_record", lambda *a, **k: {})
    from aryx.csv_bml_ingestion.options import IngestResult
    monkeypatch.setattr("aryx.csv_bml_ingestion.upload_hook.CsvBmlUploadSession", lambda ws, job=None: SimpleNamespace(
        ingest=lambda d, n: (order.append("csv"), IngestResult(source=n, status="loaded"))[1]))
    fr._run_files([(b"a,b\n1,2\n", "x.csv"), (b"<r/>", "g.xml")], "T", [], [], "job3", workspace_id=1)
    assert order == ["xml", "csv"]


# --- curated graph first, raw graph as the fallback ----------------------------------------------
def _curated_first(monkeypatch, curated_projection, raw_projection):
    from aryx.cpq_ingestion.naming import raw_workspace_id
    monkeypatch.setattr(sg, "get_cpq_ingestion_settings", lambda: SimpleNamespace(cpq_raw_workspace_offset=1_000_000_000))
    cur_db = FakeGraphDb(curated_projection, 3)                                         # curated scope = workspace id
    raw_db = FakeGraphDb(raw_projection, raw_workspace_id(3, 1_000_000_000, "some_file"))
    lk = sg.CuratedFirstLookup(None, 3)
    lk.curated, lk.raw = StoredGraphLookup(cur_db, 3, sg.CURATED), StoredGraphLookup(raw_db, 3, sg.RAW)
    lk.cur_db, lk.raw_db = cur_db, raw_db
    return lk


def test_curated_scope_is_exactly_the_workspace_id(monkeypatch, enriched):
    lk = _curated_first(monkeypatch, enriched, enriched)
    lk.lookup("attrsequence")
    assert [c[1] for c in lk.cur_db.calls if c[0] == sg._ENRICHED_SQL] == [(3, 3)]


def test_the_curated_graph_answers_and_the_raw_graph_is_not_even_read(monkeypatch, enriched):
    lk = _curated_first(monkeypatch, enriched, project_xml_to_raw_graph(XML))
    r = lk.lookup("attrSequence")
    assert r.source == "curated graph" and r.matches[0].label == "id=111"
    assert lk.raw_db.calls == []


def test_without_query_lists_in_the_curated_graph_the_raw_graph_answers(monkeypatch, enriched, caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger=sg.logger.name):
        lk = _curated_first(monkeypatch, project_xml_to_raw_graph(XML), enriched)       # curated has no lists yet
        r = lk.lookup("attrSequence")
    assert r.source == "raw graph" and r.matches[0].label == "id=111"
    assert "no query lists in its curated graph" in caplog.text


def test_when_the_curated_graph_has_lists_it_is_the_authority(monkeypatch):
    only_222 = enrich_projection(project_xml_to_raw_graph(
        b"<root><fn><id>222</id><script_text>q = \"select a from attrToPDNonFrequency where b=1\" + \"\";</script_text></fn></root>"))
    lk = _curated_first(monkeypatch, only_222, enrich_projection(project_xml_to_raw_graph(XML)))
    r = lk.lookup("attrSequence")                      # only an older raw graph knows this table
    assert r.matches == () and r.source == "curated graph"
    assert lk.raw_db.calls == []


def test_the_choice_is_made_once_per_job(monkeypatch, enriched):
    lk = _curated_first(monkeypatch, enriched, enriched)
    lk.lookup("attrsequence"); lk.lookup("attrtopdnonfrequency")
    assert len([c for c in lk.cur_db.calls if c[0] == sg._ENRICHED_SQL]) == 1


def test_the_pipeline_log_names_the_graph_that_answered(monkeypatch, enriched, tmp_path, seeded_sql_root):
    from aryx.csv_bml_ingestion import ingest_csv
    lk = _curated_first(monkeypatch, enriched, enriched)
    csv_path = write_csv(tmp_path / "attrSequence.csv", SEQ_HEADER, ["String"] * 15,
                         [["modify", "k", "M", "B", "", "", "a", "1", "R", "", "", "", "", "", ""]])
    assert ingest_csv(csv_path, lk, FakeDb()).status == "loaded"


# --- confirm step: the curated graph is built from a projection that carries the query lists ----------
def test_the_confirm_step_adds_the_query_lists_before_resolving(monkeypatch):
    from unittest.mock import MagicMock, patch
    from aryx.cpq_ingestion.raw_graph.resolve_relate import resolve_and_relate_raw_graph
    monkeypatch.setenv("ARYX_CSV_BML_ENABLED", "true")
    seen = {}

    def fake_run_pipeline(connector, **kw):
        seen.setdefault("props", []).extend(dict(r.payload) for r in connector.extract())
        return {"entities": 1, "run_id": "r1"}

    est = MagicMock()
    est.entity_ids_by_run.return_value = {}
    base = "aryx.cpq_ingestion.raw_graph.resolve_relate."
    with patch(base + "run_pipeline", side_effect=fake_run_pipeline), patch(base + "EntityStore", return_value=est), \
         patch(base + "project_workspace_graph", return_value={}), \
         patch("aryx.cpq_ingestion.raw_graph.match_key_inference.llm_runtime.chat", side_effect=RuntimeError("no llm")):
        resolve_and_relate_raw_graph(project_xml_to_raw_graph(XML), workspace_id=3, source_key="k", dsn="", graph_url="",
                                     broker=MagicMock())
    assert [p[TABLES_KEY] for p in seen["props"] if TABLES_KEY in p] == [["attrsequence"], ["attrtopdnonfrequency"]]


def test_the_confirm_step_is_unchanged_when_the_switch_is_off(monkeypatch):
    from aryx.cpq_ingestion.raw_graph.store import with_query_tables
    monkeypatch.delenv("ARYX_CSV_BML_ENABLED", raising=False)
    proj = project_xml_to_raw_graph(XML)
    assert with_query_tables(proj) is proj
