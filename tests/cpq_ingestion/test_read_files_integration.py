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
from aryx.pipeline.doc_discovery.doc_discovery import _xml_to_csvs, read_files

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
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    get_cpq_ingestion_settings.cache_clear()

    direct = _xml_to_csvs(SAMPLE_XML, "sample")

    with patch("aryx.cpq_ingestion.pipeline.project_and_write_raw_graph") as mock_write:
        mock_write.return_value = RawGraphWriteResult(
            nodes_written=3, edges_written=2, backend="falkordb", graph_ref="graph=aryx_raw_ws_50_sample",
        )
        result = read_files(
            doc_paths=[], tabular=[(SAMPLE_XML, "sample.xml")],
            broker=Broker.__new__(Broker), context="", did="test-did", workspace_id=50,
        )

    mock_write.assert_called_once()
    _, kwargs = mock_write.call_args
    assert kwargs["workspace_id"] == 50
    # Same CSV plans either way -- only the raw-graph side effect differs.
    assert len(result["tabular"]) == len(direct)


def test_read_files_forwards_the_real_workspace_id_not_a_default(monkeypatch):
    """Regression guard: workspace_id must be the caller's real value, not
    silently falling back to the default of 1 for every discovery job."""
    monkeypatch.setenv("ARYX_INGEST_FILE_TYPE", "xml")
    monkeypatch.setenv("ARYX_INGEST_PIPELINE", "cpq_ingestion")
    get_cpq_ingestion_settings.cache_clear()

    with patch("aryx.cpq_ingestion.pipeline.project_and_write_raw_graph") as mock_write:
        mock_write.return_value = RawGraphWriteResult(
            nodes_written=1, edges_written=0, backend="falkordb", graph_ref="graph=aryx_raw_ws_999_sample",
        )
        read_files(
            doc_paths=[], tabular=[(SAMPLE_XML, "sample.xml")],
            broker=Broker.__new__(Broker), context="", did="test-did", workspace_id=999,
        )

    assert mock_write.call_args.kwargs["workspace_id"] == 999


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
