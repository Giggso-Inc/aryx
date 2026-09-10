"""fn_handler.py (the OCI Functions worker entry point) silently rejected
.xml and .xlsx files -- _DATA_EXTS only listed .json/.csv, so any XML/XLSX
file routed through the OCI Functions worker backend hit _dispatch's
`else: raise ValueError("Unsupported file type")`, regardless of size.
This was invisible until file_ingest_api.py's own _MAX_FILE was raised
high enough (2026-09, see test_file_ingest_size_limits_2026_09_04.py)
that OCI Functions became a realistic path for a real 223 MB MSI catalog
export.

Ported the same expand-to-per-type-CSV + FK-auto-detect + catalog-upsert
logic file_ingest_api.py already runs locally for .xml/.xlsx into
_dispatch(), scoped to one file per invocation (OCI Functions submits one
function call per source file -- there is no cross-file batch to
consider for XML; xlsx cross-workbook FK detection is a known, disclosed
reduction in parity versus the local multi-file path, not something these
tests claim to cover).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _call_dispatch(suffix: str, file_bytes: bytes = b"<x/>") -> MagicMock:
    from aryx.worker.fn_handler_dispatch import _dispatch

    settings = MagicMock()
    settings.effective_dsn.return_value = "postgresql://x"
    settings.graph_url = "redis://x"
    broker = MagicMock()
    on_progress = MagicMock()

    _dispatch(
        suffix=suffix,
        file_bytes=file_bytes,
        filename=f"aSTRO25_ConfigData{suffix}",
        settings=settings,
        broker=broker,
        on_progress=on_progress,
        ontology_type="Product",
        match_keys=["name"],
        fk_links=[],
        workspace_id=1,
    )
    return on_progress


def test_xml_and_xlsx_extensions_are_now_dispatchable() -> None:
    """Previously: .xml/.xlsx fell through to the else-branch, raising
    ValueError("Unsupported file type: '.xml'") regardless of the file's
    content or size, before either suffix had its own elif branch."""
    with patch("aryx.pipeline.doc_discovery._xml_to_csvs", return_value=[]), \
         patch("aryx.pipeline.doc_discovery._detect_fk_links", return_value=[]), \
         patch("aryx.pipeline.orchestrate.run_pipeline") as mock_run, \
         patch("aryx.source.source_catalog.upsert_xml_catalog_entry") as mock_upsert, \
         patch("aryx.store.datasource_store.DatasourceStore"):
        _call_dispatch(".xml")  # must not raise "Unsupported file type"
    # Unlike .xlsx, the .xml branch has no "no ingestible elements" guard --
    # it always registers a catalog entry (possibly with zero assets), so
    # only assert no pipeline run happened for an empty element list.
    mock_run.assert_not_called()

    with patch("aryx.pipeline.doc_discovery._xlsx_to_csvs", return_value=[]), \
         patch("aryx.pipeline.orchestrate.run_pipeline") as mock_run, \
         patch("aryx.source.source_catalog.upsert_xlsx_catalog_entry") as mock_upsert, \
         patch("aryx.store.datasource_store.DatasourceStore"):
        _call_dispatch(".xlsx")  # must not raise "Unsupported file type"
    mock_run.assert_not_called()
    mock_upsert.assert_not_called()


def test_xml_runs_one_pipeline_pass_per_derived_type_relate_only_on_last() -> None:
    xml_csvs = [
        (b"a,b\n1,2", "aSTRO25_ConfigData_ProductLine.csv"),
        (b"c,d\n3,4", "aSTRO25_ConfigData_Attribute.csv"),
    ]
    with patch("aryx.pipeline.doc_discovery._xml_to_csvs", return_value=xml_csvs), \
         patch("aryx.pipeline.doc_discovery._detect_fk_links", return_value=[{"fake": "fk"}]), \
         patch("aryx.pipeline.orchestrate.run_pipeline") as mock_run, \
         patch("aryx.source.source_catalog.upsert_xml_catalog_entry") as mock_upsert, \
         patch("aryx.store.datasource_store.DatasourceStore"):
        _call_dispatch(".xml")

    assert mock_run.call_count == 2
    first_call, last_call = mock_run.call_args_list
    assert first_call.kwargs["relate"] is False
    assert first_call.kwargs["skip_graph"] is True
    assert first_call.kwargs["fk_links"] == []
    assert last_call.kwargs["relate"] is True
    assert last_call.kwargs["skip_graph"] is False
    assert last_call.kwargs["fk_links"] == [{"fake": "fk"}]
    mock_upsert.assert_called_once()


def test_xml_derives_ontology_type_from_element_tag() -> None:
    xml_csvs = [(b"a,b\n1,2", "aSTRO25_ConfigData_hardware_option.csv")]
    with patch("aryx.pipeline.doc_discovery._xml_to_csvs", return_value=xml_csvs), \
         patch("aryx.pipeline.doc_discovery._detect_fk_links", return_value=[]), \
         patch("aryx.pipeline.orchestrate.run_pipeline") as mock_run, \
         patch("aryx.source.source_catalog.upsert_xml_catalog_entry"), \
         patch("aryx.store.datasource_store.DatasourceStore"):
        _call_dispatch(".xml")

    assert mock_run.call_args.kwargs["ontology_type"] == "HardwareOption"


def test_xlsx_runs_one_pipeline_pass_per_sheet_relate_only_on_last() -> None:
    xlsx_csvs = [
        (b"a,b\n1,2", "aSTRO25_ConfigData__Sheet1.csv"),
        (b"c,d\n3,4", "aSTRO25_ConfigData__Sheet2.csv"),
    ]
    with patch("aryx.pipeline.doc_discovery._xlsx_to_csvs", return_value=xlsx_csvs), \
         patch("aryx.pipeline.doc_discovery._detect_fk_links", return_value=[]), \
         patch("aryx.pipeline.orchestrate.run_pipeline") as mock_run, \
         patch("aryx.source.source_catalog.upsert_xlsx_catalog_entry") as mock_upsert, \
         patch("aryx.store.datasource_store.DatasourceStore"):
        _call_dispatch(".xlsx")

    assert mock_run.call_count == 2
    assert mock_run.call_args_list[0].kwargs["relate"] is False
    assert mock_run.call_args_list[-1].kwargs["relate"] is True
    mock_upsert.assert_called_once()


def test_xlsx_with_no_ingestible_sheets_skips_pipeline_and_catalog_upsert() -> None:
    """All-hidden/empty workbook -- must not crash, must not register a
    catalog entry with zero assets."""
    with patch("aryx.pipeline.doc_discovery._xlsx_to_csvs", return_value=[]), \
         patch("aryx.pipeline.orchestrate.run_pipeline") as mock_run, \
         patch("aryx.source.source_catalog.upsert_xlsx_catalog_entry") as mock_upsert:
        _call_dispatch(".xlsx")

    mock_run.assert_not_called()
    mock_upsert.assert_not_called()


def test_unsupported_extension_still_raises() -> None:
    """Regression guard: adding .xml/.xlsx must not accidentally widen
    the else-branch to accept everything."""
    import pytest
    with pytest.raises(ValueError, match="Unsupported file type"):
        _call_dispatch(".unknownext")
