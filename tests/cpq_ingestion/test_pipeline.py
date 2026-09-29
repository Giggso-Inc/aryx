"""project_raw_graph_and_flatten — the file_ingest integration point, mocked."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from aryx.cpq_ingestion.config import get_cpq_ingestion_settings
from aryx.cpq_ingestion.pipeline import project_raw_graph_and_flatten
from aryx.cpq_ingestion.raw_graph.models import RawGraphWriteResult

SAMPLE_XML = b"<Root><Child>value</Child></Root>"


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_cpq_ingestion_settings.cache_clear()
    yield
    get_cpq_ingestion_settings.cache_clear()


def test_returns_same_shape_as_xml_to_csvs_directly():
    from aryx.pipeline.doc_discovery.doc_discovery import _xml_to_csvs

    direct = _xml_to_csvs(SAMPLE_XML, "sample")
    with patch("aryx.cpq_ingestion.pipeline.project_and_write_raw_graph") as mock_write:
        mock_write.return_value = RawGraphWriteResult(
            nodes_written=2, edges_written=1, backend="falkordb", graph_ref="graph=aryx_raw_ws_1",
        )
        via_pipeline = project_raw_graph_and_flatten(
            SAMPLE_XML, "sample", workspace_id=1, dsn="unused", graph_url="unused",
        )
    assert via_pipeline == direct


def test_writes_raw_graph_when_enabled(monkeypatch):
    monkeypatch.setenv("ARYX_CPQ_RAW_GRAPH_ENABLED", "true")
    get_cpq_ingestion_settings.cache_clear()
    with patch("aryx.cpq_ingestion.pipeline.project_and_write_raw_graph") as mock_write:
        mock_write.return_value = RawGraphWriteResult(
            nodes_written=2, edges_written=1, backend="falkordb", graph_ref="graph=aryx_raw_ws_1",
        )
        project_raw_graph_and_flatten(SAMPLE_XML, "sample", workspace_id=1, dsn="unused", graph_url="unused")
    mock_write.assert_called_once()
    _, kwargs = mock_write.call_args
    assert kwargs["workspace_id"] == 1
    assert kwargs["source_key"] == "sample"  # M1 fix: stem threaded through as the per-file scope key


def test_skips_raw_graph_when_disabled(monkeypatch):
    monkeypatch.setenv("ARYX_CPQ_RAW_GRAPH_ENABLED", "false")
    get_cpq_ingestion_settings.cache_clear()
    with patch("aryx.cpq_ingestion.pipeline.project_and_write_raw_graph") as mock_write:
        project_raw_graph_and_flatten(SAMPLE_XML, "sample", workspace_id=1, dsn="unused", graph_url="unused")
    mock_write.assert_not_called()


def test_raw_graph_failure_does_not_block_csv_ingest(monkeypatch, caplog):
    """A malformed-XML parse error (or any raw-graph-write failure) must not
    crash the upload -- _xml_to_csvs has its own, separate, graceful fallback
    for bad XML, and this best-effort layer must never regress that."""
    monkeypatch.setenv("ARYX_CPQ_RAW_GRAPH_ENABLED", "true")
    get_cpq_ingestion_settings.cache_clear()
    from aryx.pipeline.doc_discovery.doc_discovery import _xml_to_csvs

    expected = _xml_to_csvs(SAMPLE_XML, "sample")
    with patch(
        "aryx.cpq_ingestion.pipeline.project_and_write_raw_graph",
        side_effect=RuntimeError("graph store unreachable"),
    ):
        with caplog.at_level("WARNING"):
            result = project_raw_graph_and_flatten(
                SAMPLE_XML, "sample", workspace_id=1, dsn="unused", graph_url="unused",
            )
    assert result == expected
    assert any("raw graph projection/write failed" in r.message for r in caplog.records)


def test_two_files_in_one_job_use_distinct_source_keys():
    """Regression guard for Raven review M1: a job uploading two XML files
    to the same workspace must scope each file's raw-graph write by its own
    stem, not silently reuse/clear the previous file's scope."""
    with patch("aryx.cpq_ingestion.pipeline.project_and_write_raw_graph") as mock_write:
        mock_write.return_value = RawGraphWriteResult(
            nodes_written=1, edges_written=0, backend="falkordb", graph_ref="graph=aryx_raw_ws_1_fileA",
        )
        project_raw_graph_and_flatten(SAMPLE_XML, "fileA", workspace_id=1, dsn="unused", graph_url="unused")
        project_raw_graph_and_flatten(SAMPLE_XML, "fileB", workspace_id=1, dsn="unused", graph_url="unused")

    source_keys = [call.kwargs["source_key"] for call in mock_write.call_args_list]
    assert source_keys == ["fileA", "fileB"]
