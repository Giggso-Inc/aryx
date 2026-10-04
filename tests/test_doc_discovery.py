"""Tests for _xml_to_csvs, read_files, and _display_name in pipeline.doc_discovery."""
import csv
import io
from unittest.mock import MagicMock, patch

from aryx.pipeline.doc_discovery import doc_discovery
from aryx.pipeline.doc_discovery.doc_discovery import _xml_to_csvs, ingest_confirmed


def _rows(data: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(data.decode())))


def test_empty_xml_no_repeating_children_falls_back_to_raw():
    xml = b"<root></root>"
    results = _xml_to_csvs(xml, "test")
    assert results == [(xml, "test.csv")]


def test_single_repeating_tag_produces_one_csv():
    xml = b"""<root>
        <item id="1" name="alpha"/>
        <item id="2" name="beta"/>
        <item id="3" name="gamma"/>
    </root>"""
    results = _xml_to_csvs(xml, "data")
    assert len(results) == 1
    rows = _rows(results[0][0])
    assert len(rows) == 3
    assert all(r["_element_type"] == "item" for r in rows)


def test_multi_type_xml_produces_multiple_csvs():
    xml = b"""<catalogue>
        <product id="p1" name="Widget"/>
        <product id="p2" name="Gadget"/>
        <category id="c1" label="Electronics"/>
        <category id="c2" label="Tools"/>
    </catalogue>"""
    results = _xml_to_csvs(xml, "catalogue")
    types_found = {name.rsplit("_", 1)[-1].replace(".csv", "") for _, name in results}
    assert "product" in types_found
    assert "category" in types_found


def test_namespace_prefixed_tags_are_stripped():
    xml = b"""<root xmlns:ns="urn:test">
        <ns:Widget id="1"/>
        <ns:Widget id="2"/>
        <ns:Widget id="3"/>
    </root>"""
    results = _xml_to_csvs(xml, "ns_test")
    assert len(results) == 1
    rows = _rows(results[0][0])
    assert all(r["_element_type"] == "Widget" for r in rows)


def test_elements_with_text_only_use_text_field():
    xml = b"""<root>
        <note>alpha</note>
        <note>beta</note>
        <note>gamma</note>
    </root>"""
    results = _xml_to_csvs(xml, "notes")
    assert len(results) == 1
    rows = _rows(results[0][0])
    assert all(r.get("_text") for r in rows)


def test_malformed_xml_falls_back_to_raw_bytes():
    bad = b"<root><unclosed>"
    results = _xml_to_csvs(bad, "broken")
    assert len(results) == 1
    assert results[0][0] == bad


def test_fk_column_injected_from_parent():
    xml = b"""<store id="s1">
        <product id="p1" name="Widget"/>
        <product id="p2" name="Gadget"/>
    </store>"""
    results = _xml_to_csvs(xml, "store")
    assert len(results) == 1
    rows = _rows(results[0][0])
    assert all(r.get("store_id") == "s1" for r in rows)


# ── read_files: XML match_keys override ──────────────────────────────────────

def test_xml_derived_plans_get_text_match_key():
    # When an XML file is expanded into CSVs, _infer_type may return match_keys
    # based on the CSV sample (often ["name"] since that's the LLM fallback).
    # read_files must override match_keys to ["_text"] for every XML-derived CSV
    # because XML CSVs have no "name" column — only "_text" for the entity value.
    xml = b"""<Catalogue>
        <Product name="Widget">foo</Product>
        <Product name="Gadget">bar</Product>
        <Product name="Doohickey">baz</Product>
    </Catalogue>"""

    mock_settings = MagicMock()
    mock_settings.rdb_dsn = "mock://db"
    mock_settings.chunk_size = 500
    mock_settings.chunk_overlap = 50
    mock_settings.embed_dim = 1536

    # _infer_type would normally return ["name"] as fallback — the override must win.
    with patch("aryx.pipeline.doc_discovery.doc_discovery.get_settings", return_value=mock_settings), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._infer_type",
               return_value={"ontology_type": "Product", "match_keys": ["name"]}):
        from aryx.pipeline.doc_discovery.doc_discovery import read_files
        result = read_files(
            doc_paths=[],
            tabular=[(xml, "catalogue.xml")],
            broker=MagicMock(),
            context="",
        )

    for plan in result["tabular"]:
        assert plan["match_keys"] == ["_text"], (
            f"XML-derived plan '{plan['filename']}' should have match_keys=['_text'], "
            f"got {plan['match_keys']}"
        )


# ── _display_name: _text key and underscore-prefix skip ──────────────────────

def test_display_name_uses_text_key():
    from aryx.graph.falkor_store import _display_name as falkor_dn
    from aryx.graph.oracle_graph_store import _display_name as oracle_dn

    attrs = {"_element_type": "Product", "_text": "TechCorp Global Industries"}
    assert falkor_dn(attrs) == "TechCorp Global Industries"
    assert oracle_dn(attrs) == "TechCorp Global Industries"


def test_display_name_skips_underscore_prefixed_keys_in_fallback():
    # When no key from _NAME_KEYS matches, the fallback loop must skip _-prefixed
    # attributes (like _element_type) to avoid returning tag names as display labels.
    from aryx.graph.falkor_store import _display_name as falkor_dn
    from aryx.graph.oracle_graph_store import _display_name as oracle_dn

    attrs = {"_element_type": "Supplier", "_some_meta": "internal", "ref": "SUP-001"}
    # "ref" is in _NAME_KEYS — should be found before fallback loop runs.
    assert falkor_dn(attrs) == "SUP-001"
    assert oracle_dn(attrs) == "SUP-001"


def test_display_name_fallback_skips_underscore_no_named_key():
    # No _NAME_KEYS match; fallback loop must skip _ keys and pick the first
    # short plain-string value instead of returning the tag name.
    from aryx.graph.falkor_store import _display_name as falkor_dn
    from aryx.graph.oracle_graph_store import _display_name as oracle_dn

    attrs = {"_element_type": "Supplier", "_meta": "noise", "company": "Acme Corp"}
    assert falkor_dn(attrs) == "Acme Corp"
    assert oracle_dn(attrs) == "Acme Corp"


# docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md -- widening the CPQ
# rule/table caches' TTLs from 30s to 300s only stays safe against a
# mid-session re-ingest if staleness is cleared at the point ingestion
# actually completes, not left to the (now longer) TTL alone.

class _FakeSettings:
    rdb_dsn = "postgresql://fake"
    graph_url = "redis://fake"
    ingest_relate = False
    ingest_workers = 1


def test_ingest_confirmed_clears_cpq_rule_and_table_caches_on_completion():
    """A minimal (nothing to actually ingest) call still reaches the very
    end of ingest_confirmed -- all five CPQ cache-clear hooks must fire
    there regardless, since a re-ingest into a workspace with genuinely new
    types/files takes the exact same path to completion. 2026-08-28: the two
    newer caches (_data_table_forced_vns / _substitute_util_get_constraint_
    vals, added for the /ask/threads/message concurrency fix) were
    originally missed here -- caught by review, added alongside the
    original three siblings."""
    with patch.object(doc_discovery, "get_settings", return_value=_FakeSettings()), \
         patch.object(doc_discovery, "DatasourceStore", lambda dsn: MagicMock()), \
         patch.object(doc_discovery, "_persist_tabular_sources", lambda *a, **k: None), \
         patch.object(doc_discovery, "_detect_fk_links", return_value=[]), \
         patch.object(doc_discovery, "_detect_script_data_flow_links", return_value=[]), \
         patch("aryx.cpq.data_table.data_table_resolver._clear_tables_cache") as mock_tables, \
         patch("aryx.cpq.engine._clear_rule_join_data_cache") as mock_rule_join, \
         patch("aryx.cpq.engine._clear_value_rules_cache") as mock_value_rules, \
         patch("aryx.cpq.engine._clear_data_table_forced_vns_cache") as mock_forced_vns, \
         patch("aryx.cpq.engine._clear_substitute_util_get_constraint_vals_cache") as mock_constraint_vals, \
         patch("aryx.store.pool.get_pool", return_value=MagicMock()):
        ingest_confirmed(
            data={"mentions": [], "tabular": []},
            approved_types=[], approved_files=[], broker=MagicMock(),
            jobs=MagicMock(), job_id="test-job", workspace_id=1,
        )
    mock_tables.assert_called_once()
    mock_rule_join.assert_called_once()
    mock_value_rules.assert_called_once()
    mock_forced_vns.assert_called_once()
    mock_constraint_vals.assert_called_once()


def test_ingest_confirmed_writes_cross_process_invalidation_marker():
    """2026-08-29 (PR #287 review, Section 12): the in-process clears
    above only reach THIS process' cache copy -- under multiple api
    worker processes, this write is what lets every OTHER worker notice
    a re-ingest it didn't itself handle."""
    mock_cursor = MagicMock()
    mock_cursor.__enter__.return_value = mock_cursor
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn

    with patch.object(doc_discovery, "get_settings", return_value=_FakeSettings()), \
         patch.object(doc_discovery, "DatasourceStore", lambda dsn: MagicMock()), \
         patch.object(doc_discovery, "_persist_tabular_sources", lambda *a, **k: None), \
         patch.object(doc_discovery, "_detect_fk_links", return_value=[]), \
         patch.object(doc_discovery, "_detect_script_data_flow_links", return_value=[]), \
         patch("aryx.store.pool.get_pool", return_value=mock_pool):
        ingest_confirmed(
            data={"mentions": [], "tabular": []},
            approved_types=[], approved_files=[], broker=MagicMock(),
            jobs=MagicMock(), job_id="marker-test-job", workspace_id=1,
        )
    mock_cursor.execute.assert_called_once()
    sql, params = mock_cursor.execute.call_args[0]
    assert "cpq_cache_invalidation_marker" in sql
    assert "marker-test-job" in params


def test_ingest_confirmed_marker_write_failure_never_fails_the_ingest():
    """Separate try/except from the in-process clears -- a marker-write
    failure (e.g. the migration hasn't run, or the DB is unreachable)
    must never surface as an ingest failure."""
    with patch.object(doc_discovery, "get_settings", return_value=_FakeSettings()), \
         patch.object(doc_discovery, "DatasourceStore", lambda dsn: MagicMock()), \
         patch.object(doc_discovery, "_persist_tabular_sources", lambda *a, **k: None), \
         patch.object(doc_discovery, "_detect_fk_links", return_value=[]), \
         patch.object(doc_discovery, "_detect_script_data_flow_links", return_value=[]), \
         patch("aryx.cpq.data_table.data_table_resolver._clear_tables_cache"), \
         patch("aryx.cpq.engine._clear_rule_join_data_cache"), \
         patch("aryx.cpq.engine._clear_value_rules_cache"), \
         patch("aryx.cpq.engine._clear_data_table_forced_vns_cache"), \
         patch("aryx.cpq.engine._clear_substitute_util_get_constraint_vals_cache"), \
         patch("aryx.store.pool.get_pool", side_effect=RuntimeError("db unreachable")):
        # Must not raise despite the marker-write failure above.
        ingest_confirmed(
            data={"mentions": [], "tabular": []},
            approved_types=[], approved_files=[], broker=MagicMock(),
            jobs=MagicMock(), job_id="test-job", workspace_id=1,
        )


def test_ingest_confirmed_cache_invalidation_failure_never_fails_the_ingest():
    """Best-effort per its own comment -- an import failure or a clear()
    bug in the invalidation hook must never surface as an ingest failure."""
    with patch.object(doc_discovery, "get_settings", return_value=_FakeSettings()), \
         patch.object(doc_discovery, "DatasourceStore", lambda dsn: MagicMock()), \
         patch.object(doc_discovery, "_persist_tabular_sources", lambda *a, **k: None), \
         patch.object(doc_discovery, "_detect_fk_links", return_value=[]), \
         patch.object(doc_discovery, "_detect_script_data_flow_links", return_value=[]), \
         patch(
             "aryx.cpq.data_table.data_table_resolver._clear_tables_cache",
             side_effect=RuntimeError("cache backend unavailable"),
         ), \
         patch("aryx.store.pool.get_pool", return_value=MagicMock()):
        # Must not raise despite the cache-clear failure above.
        ingest_confirmed(
            data={"mentions": [], "tabular": []},
            approved_types=[], approved_files=[], broker=MagicMock(),
            jobs=MagicMock(), job_id="test-job", workspace_id=1,
        )


# ── CPQ layout files surfaced through the Documents read/confirm flow ──────
# CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md: .txt/.json layout
# exports are neither DOC_EXTS nor DATA_EXTS, so doc_discover_read_job.py
# pulls them out up front (see cpq_layout_upload_active()) and passes them
# to read_files() as layout_items -- surfaced here as ordinary "tabular"
# plans (kind="cpq_layout") so this screen's existing read-then-confirm UX
# applies to them unchanged, with the actual DB write deferred to confirm.

def test_read_files_surfaces_layout_items_as_cpq_layout_plans():
    from aryx.pipeline.doc_discovery.doc_discovery import read_files

    mock_settings = MagicMock()
    mock_settings.chunk_size = 500
    mock_settings.chunk_overlap = 50
    mock_settings.embed_dim = 1536

    layout_data = b'{"status": "Active"}'
    with patch("aryx.pipeline.doc_discovery.doc_discovery.get_settings", return_value=mock_settings):
        result = read_files(
            doc_paths=[], tabular=[], broker=MagicMock(), context="",
            layout_items=[(layout_data, "Config Layout APX Next.txt")],
        )

    assert len(result["tabular"]) == 1
    plan = result["tabular"][0]
    assert plan["filename"] == "Config Layout APX Next.txt"
    assert plan["data"] == layout_data
    assert plan["kind"] == "cpq_layout"
    assert plan["ontology_type"] == "CPQ Layout File"
    assert result["summary"]["files"] == [
        {"filename": "Config Layout APX Next.txt", "ontology_type": "CPQ Layout File"},
    ]


class _FakeSettingsWithDsn(_FakeSettings):
    """_FakeSettings lacks effective_dsn() (a pre-existing gap unrelated to
    this test -- see the 4 already-failing test_ingest_confirmed_* tests
    above); the new cpq_layout store_layout_file() call needs it, so this
    subclass adds it without touching the shared fixture."""
    def effective_dsn(self) -> str:
        return "postgresql://fake"


def test_ingest_confirmed_stores_approved_layout_plan_via_store_layout_file():
    layout_data = b'{"status": "Active"}'
    data = {
        "mentions": [],
        "tabular": [{
            "filename": "Config Layout APX Next.txt", "data": layout_data,
            "ontology_type": "CPQ Layout File", "kind": "cpq_layout",
        }],
    }
    with patch.object(doc_discovery, "get_settings", return_value=_FakeSettingsWithDsn()), \
         patch.object(doc_discovery, "DatasourceStore", lambda dsn: MagicMock()), \
         patch.object(doc_discovery, "_persist_tabular_sources") as mock_persist, \
         patch.object(doc_discovery, "_detect_fk_links", return_value=[]), \
         patch.object(doc_discovery, "_detect_script_data_flow_links", return_value=[]), \
         patch("aryx.cpq_ingestion.layout_store.store_layout_file",
               return_value="Config Layout APX Next") as mock_store, \
         patch("aryx.store.pool.get_pool", return_value=MagicMock()):
        ingest_confirmed(
            data=data,
            approved_types=[], approved_files=["Config Layout APX Next.txt"],
            broker=MagicMock(), jobs=MagicMock(), job_id="layout-confirm-job",
            workspace_id=7,
        )

    mock_store.assert_called_once()
    _args, kwargs = mock_store.call_args
    assert _args[0] == layout_data
    assert _args[1] == "Config Layout APX Next.txt"
    assert kwargs["workspace_id"] == 7
    # The layout plan must never reach _persist_tabular_sources -- it isn't
    # CSV/JSON tabular data, and that function assumes source_filename/
    # source_bytes fields a layout plan doesn't have.
    mock_persist.assert_called_once_with([], 7, "postgresql://fake")


def test_ingest_confirmed_routes_cpq_raw_graph_preview_plan_to_resolve_relate(monkeypatch):
    """Integration-level guard for the Read-stage preview plan's shape
    (PR #426 review, "no ingest_confirmed-level test"): a cpq_raw_graph_preview
    plan must (1) reach resolve_and_relate_raw_graph via
    partition_cpq_ingestion_plans -- never the FK-guessing valid_plans path --
    and (2) be catalogued by the real _persist_tabular_sources with
    assets=[], not the fake summary.csv as a real generated asset."""
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
    get_cpq_ingestion_settings.cache_clear()

    preview_plan = {
        "filename": "order.summary.csv",
        "data": b"nodes,edges\n4,3\n",
        "ontology_type": "4 nodes / 3 edges",
        "match_keys": [],
        "source_filename": "order.xml",
        "source_bytes": b"<Root><Child/></Root>",
        "cpq_raw_graph_preview": True,
    }
    data = {"mentions": [], "tabular": [preview_plan]}

    with patch.object(doc_discovery, "get_settings", return_value=_FakeSettingsWithDsn()), \
         patch.object(doc_discovery, "DatasourceStore", lambda dsn: MagicMock()), \
         patch("aryx.pipeline.doc_discovery.doc_discovery_persist.DatasourceStore"), \
         patch("aryx.pipeline.doc_discovery.doc_discovery_persist.upsert_xml_catalog_entry") as mock_upsert, \
         patch.object(doc_discovery, "_detect_fk_links", return_value=[]), \
         patch.object(doc_discovery, "_detect_script_data_flow_links", return_value=[]), \
         patch("aryx.cpq_ingestion.raw_graph.xml_projector.project_xml_to_raw_graph") as mock_project, \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.resolve_and_relate_raw_graph") as mock_resolve, \
         patch("aryx.store.pool.get_pool", return_value=MagicMock()):
        mock_resolve.return_value = {"resolved": 4}
        ingest_confirmed(
            data=data,
            approved_types=[], approved_files=["order.summary.csv"],
            broker=MagicMock(), jobs=MagicMock(), job_id="cpq-preview-confirm-job",
            workspace_id=3,
        )

    # §3b (2026-10-04): doc_discovery.py no longer calls project_xml_to_
    # raw_graph directly -- it hands raw bytes to resolve_and_relate_raw_
    # graph() via xml_bytes, which decides internally whether to parse
    # eagerly or stream.
    mock_project.assert_not_called()
    mock_resolve.assert_called_once()
    _, resolve_kwargs = mock_resolve.call_args
    assert resolve_kwargs["xml_bytes"] == preview_plan["source_bytes"]
    assert callable(resolve_kwargs["should_stop"])
    _, resolve_kwargs = mock_resolve.call_args
    assert resolve_kwargs["workspace_id"] == 3
    assert resolve_kwargs["source_key"] == "order"

    mock_upsert.assert_called_once()
    _, upsert_kwargs = mock_upsert.call_args
    assert upsert_kwargs["source_filename"] == "order.xml"
    assert upsert_kwargs["assets"] == []


def _cpq_preview_plan(filename="order.summary.csv", source_filename="order.xml"):
    return {
        "filename": filename,
        "data": b"nodes,edges\n4,3\n",
        "ontology_type": "4 nodes / 3 edges",
        "match_keys": [],
        "source_filename": source_filename,
        "source_bytes": b"<Root><Child/></Root>",
        "cpq_raw_graph_preview": True,
    }


def test_ingest_confirmed_cpq_source_file_marks_complete_and_persists_state(monkeypatch):
    """§5 of docs/ingestion/CPQ_XML_CONFIRM_RESOLVE_PERFORMANCE_ISSUES_
    2026-10-04.md: the cpq_ingestion loop previously never participated in
    completed_plans tracking at all, unlike the generic CSV/_run_one_plan
    path -- a discovery_id was given, but a crash mid-run (or a later
    re-confirm) always re-resolved every tag from scratch. Now it must
    persist state exactly like _run_one_plan does."""
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
    get_cpq_ingestion_settings.cache_clear()

    preview_plan = _cpq_preview_plan()
    data = {"mentions": [], "tabular": [preview_plan]}

    with patch.object(doc_discovery, "get_settings", return_value=_FakeSettingsWithDsn()), \
         patch.object(doc_discovery, "DatasourceStore", lambda dsn: MagicMock()), \
         patch("aryx.pipeline.doc_discovery.doc_discovery_persist.DatasourceStore"), \
         patch("aryx.pipeline.doc_discovery.doc_discovery_persist.upsert_xml_catalog_entry"), \
         patch.object(doc_discovery, "_detect_fk_links", return_value=[]), \
         patch.object(doc_discovery, "_detect_script_data_flow_links", return_value=[]), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.resolve_and_relate_raw_graph") as mock_resolve, \
         patch.object(doc_discovery, "_update_confirm_state") as mock_update_state, \
         patch("aryx.store.pool.get_pool", return_value=MagicMock()):
        mock_resolve.return_value = {"resolved": 4}
        ingest_confirmed(
            data=data,
            approved_types=[], approved_files=["order.summary.csv"],
            broker=MagicMock(), jobs=MagicMock(), job_id="cpq-resume-confirm-job",
            workspace_id=3, discovery_id="disc-1",
        )

    mock_resolve.assert_called_once()
    mock_update_state.assert_called_once()
    disc_id, state = mock_update_state.call_args[0]
    assert disc_id == "disc-1"
    assert state["completed_plans"] == ["order.xml"]


def test_ingest_confirmed_skips_already_completed_cpq_source_file_on_resume(monkeypatch):
    """Resuming a discovery whose confirm_state already lists this XML
    file's source_filename as completed must skip it entirely -- not
    re-resolve it and duplicate every entity. Keyed by source_filename
    (what completed_plans now stores for cpq files), not plan["filename"]
    (the per-tag-derived CSV name the generic tabular filter checks, a
    different key space that would never match)."""
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
    get_cpq_ingestion_settings.cache_clear()

    preview_plan = _cpq_preview_plan()
    data = {"mentions": [], "tabular": [preview_plan]}

    with patch.object(doc_discovery, "get_settings", return_value=_FakeSettingsWithDsn()), \
         patch.object(doc_discovery, "DatasourceStore", lambda dsn: MagicMock()), \
         patch("aryx.pipeline.doc_discovery.doc_discovery_persist.DatasourceStore"), \
         patch.object(doc_discovery, "_detect_fk_links", return_value=[]), \
         patch.object(doc_discovery, "_detect_script_data_flow_links", return_value=[]), \
         patch("aryx.cpq_ingestion.raw_graph.resolve_relate.resolve_and_relate_raw_graph") as mock_resolve, \
         patch.object(doc_discovery, "_update_confirm_state") as mock_update_state, \
         patch("aryx.store.pool.get_pool", return_value=MagicMock()):
        ingest_confirmed(
            data=data,
            approved_types=[], approved_files=["order.summary.csv"],
            broker=MagicMock(), jobs=MagicMock(), job_id="cpq-resume-confirm-job-2",
            workspace_id=3, discovery_id="disc-1",
            confirm_state={"completed_plans": ["order.xml"]},
        )

    mock_resolve.assert_not_called()
    # Nothing new to persist -- the file was already done before this run started.
    mock_update_state.assert_not_called()


def test_ingest_confirmed_skips_layout_file_too_large_without_failing():
    from aryx.cpq_ingestion.layout_store import CpqLayoutFileTooLarge

    data = {
        "mentions": [],
        "tabular": [{
            "filename": "big.txt", "data": b"x",
            "ontology_type": "CPQ Layout File", "kind": "cpq_layout",
        }],
    }
    with patch.object(doc_discovery, "get_settings", return_value=_FakeSettingsWithDsn()), \
         patch.object(doc_discovery, "DatasourceStore", lambda dsn: MagicMock()), \
         patch.object(doc_discovery, "_persist_tabular_sources", lambda *a, **k: None), \
         patch.object(doc_discovery, "_detect_fk_links", return_value=[]), \
         patch.object(doc_discovery, "_detect_script_data_flow_links", return_value=[]), \
         patch("aryx.cpq_ingestion.layout_store.store_layout_file",
               side_effect=CpqLayoutFileTooLarge("too big")), \
         patch("aryx.store.pool.get_pool", return_value=MagicMock()):
        # Must not raise despite the oversized layout file.
        ingest_confirmed(
            data=data,
            approved_types=[], approved_files=["big.txt"],
            broker=MagicMock(), jobs=MagicMock(), job_id="test-job",
            workspace_id=1,
        )
