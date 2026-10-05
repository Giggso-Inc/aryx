"""read_files() -- the real UI-facing discovery entry point ("Documents" tab
-> /api/admin/docs/read) -- routes XML through cpq_ingestion when active.

Before this, only file_ingest_run.py's _run_files() (the /admin/ingest/file
endpoint, which the deployed frontend's UI does not call for XML uploads)
checked cpq_ingestion_pipeline_active(). This left the actual, UI-reachable
XML path (read_files() -> ingest_confirmed()) permanently on the legacy
_xml_to_csvs() path regardless of env vars. Fixed by adding the same check
here, with the same drop-in-replacement contract used at the other call site.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from aryx.broker import Broker
from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
from aryx.cpq_ingestion.raw_graph.models import RawGraphWriteResult
from aryx.pipeline.doc_discovery.doc_discovery import read_files

SAMPLE_XML = b"""<root>
    <item id="1" name="alpha"/>
    <item id="2" name="beta"/>
</root>"""


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_cpq_ingestion_settings.cache_clear()
    yield
    get_cpq_ingestion_settings.cache_clear()


def test_read_files_uses_legacy_xml_to_csvs_when_pipeline_inactive(monkeypatch):
    monkeypatch.delenv("ARYX_INGEST_FILE_TYPE", raising=False)
    monkeypatch.delenv("ARYX_INGEST_PIPELINE", raising=False)
    with patch("aryx.cpq_ingestion.pipeline.project_and_write_raw_graph") as mock_write:
        result = read_files(
            doc_paths=[], tabular=[(SAMPLE_XML, "sample.xml")],
            broker=Broker.__new__(Broker), context="", did="test-did", workspace_id=50,
        )
    mock_write.assert_not_called()
    assert len(result["tabular"]) == 1
    assert result["tabular"][0]["ontology_type"]


def test_read_files_routes_xml_through_cpq_ingestion_when_active(monkeypatch):
    """When the pipeline is active, read_files() must NOT write the raw
    graph to Oracle/FalkorDB at all (removed entirely -- Confirm time
    re-derives and writes the same data from scratch regardless, see
    preview_raw_graph_counts's docstring) -- it only parses for a node/edge
    count preview, surfaced as a single synthetic plan's ontology_type."""
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    get_cpq_ingestion_settings.cache_clear()

    with patch("aryx.cpq_ingestion.pipeline.project_and_write_raw_graph") as mock_write:
        result = read_files(
            doc_paths=[], tabular=[(SAMPLE_XML, "sample.xml")],
            broker=Broker.__new__(Broker), context="", did="test-did", workspace_id=50,
        )

    mock_write.assert_not_called()
    assert len(result["tabular"]) == 1
    plan = result["tabular"][0]
    assert plan["source_filename"] == "sample.xml"
    assert plan["source_bytes"] == SAMPLE_XML
    assert "nodes" in plan["ontology_type"] and "edges" in plan["ontology_type"]


def test_read_files_is_the_same_fast_preview_whether_csv_bml_is_enabled_or_not(monkeypatch):
    """ARYX_CSV_BML_ENABLED must not change how an XML upload is read: the query lists the CSV step searches are
    added at Confirm time onto the curated graph, so Read never needs the raw-graph write (which took minutes on a
    large file). Same result with the switch on and off: no write, one synthetic counts-only preview plan."""
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    results = {}
    for switch in ("true", "false"):
        monkeypatch.setenv("ARYX_CSV_BML_ENABLED", switch)
        get_cpq_ingestion_settings.cache_clear()
        with patch("aryx.cpq_ingestion.pipeline.project_and_write_raw_graph") as mock_write, \
             patch("aryx.cpq_ingestion.pipeline.project_raw_graph_and_flatten") as mock_flatten:
            results[switch] = read_files(
                doc_paths=[], tabular=[(SAMPLE_XML, "sample.xml")],
                broker=Broker.__new__(Broker), context="", did="test-did", workspace_id=50,
            )
        mock_write.assert_not_called()
        mock_flatten.assert_not_called()
        (plan,) = results[switch]["tabular"]
        assert plan["cpq_raw_graph_preview"] is True and plan["source_filename"] == "sample.xml"
    assert results["true"]["tabular"] == results["false"]["tabular"]


def test_read_files_ignores_workspace_id_for_the_cpq_xml_preview(monkeypatch):
    """Regression guard, updated: workspace_id used to be forwarded to the
    raw-graph write (see git history); that write no longer exists for this
    path, so workspace_id has nothing left to reach here. This just confirms
    passing an arbitrary workspace_id doesn't raise or otherwise misbehave."""
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    get_cpq_ingestion_settings.cache_clear()

    with patch("aryx.cpq_ingestion.pipeline.project_and_write_raw_graph") as mock_write:
        result = read_files(
            doc_paths=[], tabular=[(SAMPLE_XML, "sample.xml")],
            broker=Broker.__new__(Broker), context="", did="test-did", workspace_id=999,
        )

    mock_write.assert_not_called()
    assert len(result["tabular"]) == 1


def test_read_files_defaults_workspace_id_to_one_for_backward_compatibility():
    """Every pre-existing caller of read_files() omits workspace_id --
    confirm the new parameter doesn't break them (defaults to 1, matching
    every other function in this codebase's workspace_id convention)."""
    import inspect

    sig = inspect.signature(read_files)
    assert sig.parameters["workspace_id"].default == 1


def test_summary_files_surfaces_the_real_uploaded_xml_filename():
    """UI regression guard: the "Review discovered types" screen renders
    summary["files"][i]["filename"] verbatim (see DocsSummaryStep.tsx). For
    an XML upload that's internally split into one synthetic
    "<stem>_<Tag>.csv" plan per discovered element type -- showing that
    synthetic name made every XML upload look like it had silently turned
    into a CSV file, even though the actual ingested bytes are still the
    original XML (source_bytes). The frontend now prefers
    source_filename when present; this confirms the backend puts it there."""
    with patch("aryx.cpq_ingestion.pipeline.project_and_write_raw_graph") as mock_write:
        mock_write.return_value = RawGraphWriteResult(
            nodes_written=2, edges_written=0, backend="falkordb", graph_ref="graph=x",
        )
        result = read_files(
            doc_paths=[], tabular=[(SAMPLE_XML, "sample.xml")],
            broker=Broker.__new__(Broker), context="", did="test-did", workspace_id=50,
        )

    files = result["summary"]["files"]
    assert len(files) >= 1
    for f in files:
        assert f["source_filename"] == "sample.xml"
        assert f["filename"] != "sample.xml"  # the synthetic per-tag name, still distinct
        assert f["filename"].endswith(".csv")  # confirms this guard targets the real leak


def test_summary_files_omits_source_filename_for_a_plain_csv_upload():
    """A plain CSV upload has no "parent" file -- filename IS the real
    upload, so source_filename must not be fabricated for it (would make
    the UI display something misleading instead of just omitting the key,
    which DiscoverySummary's TS type already treats as optional)."""
    from aryx.pipeline.doc_discovery.doc_discovery import read_files as _read_files

    result = _read_files(
        doc_paths=[], tabular=[(b"id,name\n1,Widget\n", "plain.csv")],
        broker=Broker.__new__(Broker), context="", did="test-did",
    )

    files = result["summary"]["files"]
    assert len(files) == 1
    assert files[0]["filename"] == "plain.csv"
    assert "source_filename" not in files[0]
