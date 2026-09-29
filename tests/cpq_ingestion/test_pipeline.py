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


def test_skips_raw_graph_when_disabled(monkeypatch):
    monkeypatch.setenv("ARYX_CPQ_RAW_GRAPH_ENABLED", "false")
    get_cpq_ingestion_settings.cache_clear()
    with patch("aryx.cpq_ingestion.pipeline.project_and_write_raw_graph") as mock_write:
        project_raw_graph_and_flatten(SAMPLE_XML, "sample", workspace_id=1, dsn="unused", graph_url="unused")
    mock_write.assert_not_called()
