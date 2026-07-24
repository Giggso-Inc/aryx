"""Tests for multi-sheet Excel (.xlsx) ingestion.

Zero-hardcoding contract, matching tests/cpq_fixtures.py's own stated policy:
every workbook/sheet used here is generated in-memory by the test itself via
openpyxl — no fixture .xlsx file, no hardcoded sheet-name-to-type mapping.
Each worksheet becomes its own dataset via the exact same run_pipeline()
loop, FK-auto-detection, and asset-tracking machinery already used for
multi-entity XML uploads (_xml_to_csvs's established pattern) — see
_xlsx_to_csvs in src/aryx/pipeline/doc_discovery.py and its wiring into
_run_files() in src/aryx/api/file_ingest_api.py.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from openpyxl import Workbook

from aryx.pipeline.doc_discovery import _sheet_slug, _stem_type, _xlsx_to_csvs


def _workbook_bytes(sheets: dict[str, list[list]], hidden: set[str] | None = None) -> bytes:
    """Build an .xlsx workbook in memory: {sheet_title: [[row1...], [row2...]]}."""
    hidden = hidden or set()
    wb = Workbook()
    wb.remove(wb.active)  # start with zero sheets, add only what's requested
    for title, rows in sheets.items():
        ws = wb.create_sheet(title=title)
        for row in rows:
            ws.append(row)
        if title in hidden:
            ws.sheet_state = "hidden"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── _xlsx_to_csvs: sheet extraction ─────────────────────────────────────────

def test_single_sheet_workbook_produces_one_csv():
    data = _workbook_bytes({"Customers": [
        ["customer_id", "name"], [1, "Acme"], [2, "Globex"],
    ]})
    results = _xlsx_to_csvs(data, "upload")
    assert len(results) == 1
    csv_bytes, csv_name = results[0]
    assert csv_name == "upload__Customers.csv"
    text = csv_bytes.decode("utf-8")
    assert "customer_id" in text and "Acme" in text and "Globex" in text


def test_multi_sheet_workbook_produces_one_csv_per_sheet():
    data = _workbook_bytes({
        "Customers": [["customer_id", "name"], [1, "Acme"]],
        "Orders": [["order_id", "customer_id", "amount"], [100, 1, "50.00"]],
        "Products": [["sku", "title"], ["P1", "Widget"]],
    })
    results = _xlsx_to_csvs(data, "Q3Export")
    names = sorted(n for _d, n in results)
    assert names == ["Q3Export__Customers.csv", "Q3Export__Orders.csv", "Q3Export__Products.csv"]
    # Every dataset name is traceable back to the parent workbook via the
    # shared stem prefix — the "maintain association with parent workbook"
    # requirement.
    assert all(n.startswith("Q3Export__") for n in names)


def test_hidden_sheet_is_skipped():
    data = _workbook_bytes(
        {"Visible": [["id"], [1]], "Secret": [["id"], [2]]},
        hidden={"Secret"},
    )
    results = _xlsx_to_csvs(data, "wb")
    names = [n for _d, n in results]
    assert names == ["wb__Visible.csv"]


def test_completely_empty_sheet_is_skipped():
    data = _workbook_bytes({"HasData": [["id"], [1]], "Empty": []})
    results = _xlsx_to_csvs(data, "wb")
    names = [n for _d, n in results]
    assert names == ["wb__HasData.csv"]


def test_header_only_sheet_is_skipped():
    """A template/placeholder tab with a header row but zero data rows must
    not be ingested as a garbage dataset."""
    data = _workbook_bytes({
        "Template": [["col_a", "col_b"]],  # header only, no data rows
        "Real": [["col_a", "col_b"], [1, 2]],
    })
    results = _xlsx_to_csvs(data, "wb")
    names = [n for _d, n in results]
    assert names == ["wb__Real.csv"]


def test_sheet_title_with_spaces_and_punctuation_is_slugged():
    data = _workbook_bytes({"Order Items (2024)!": [["id"], [1]]})
    results = _xlsx_to_csvs(data, "wb")
    _csv_data, csv_name = results[0]
    # No raw spaces/punctuation survive into the dataset filename.
    assert " " not in csv_name and "(" not in csv_name and "!" not in csv_name
    assert csv_name.startswith("wb__Order_Items")


def test_blank_rows_between_data_rows_are_skipped_not_treated_as_data():
    data = _workbook_bytes({"Sheet1": [
        ["id", "name"], [1, "A"], [None, None], [2, "B"],
    ]})
    csv_bytes, _name = _xlsx_to_csvs(data, "wb")[0]
    text = csv_bytes.decode("utf-8")
    # Exactly 2 real data rows + 1 header = 3 lines, not 4.
    assert len([ln for ln in text.splitlines() if ln.strip()]) == 3


# ── _sheet_slug: filename-safety helper ─────────────────────────────────────

def test_sheet_slug_handles_only_punctuation():
    assert _sheet_slug("!!!") == "Sheet"


def test_sheet_slug_is_idempotent_on_already_clean_names():
    assert _sheet_slug("Customers") == "Customers"


# ── Dynamic ontology-type derivation — no hardcoded sheet-name list ─────────

def test_novel_sheet_name_never_seen_before_still_derives_a_sensible_type():
    """Proves there is no hardcoded sheet-name-to-type table: a sheet title
    invented purely for this test resolves to a PascalCase singular type
    via the same _stem_type() inference filenames already use (word-split
    on "_"/"-", exactly like a CSV/XML filename stem would be)."""
    novel_title = "zorbax_widget_inventories"
    result = _stem_type(novel_title)
    assert result == "ZorbaxWidgetInventory"  # plural "inventories" singularized

    plural_title = "quarterly_shipment_records"
    result2 = _stem_type(plural_title)
    assert result2 and result2[0].isupper()
    assert "_" not in result2


# ── _run_files() integration: xlsx branch wiring ────────────────────────────

@pytest.fixture()
def two_sheet_xlsx_bytes():
    return _workbook_bytes({
        "Customers": [["customer_id", "name"], [1, "Acme"], [2, "Globex"]],
        "Orders": [["order_id", "customer_id", "amount"], [100, 1, "50.00"], [101, 2, "75.00"]],
    })


def test_run_files_xlsx_branch_ingests_one_sheet_per_dataset(two_sheet_xlsx_bytes, monkeypatch):
    """Each worksheet must go through its own run_pipeline() call, exactly
    like the existing multi-file-CSV and multi-type-XML paths."""
    import aryx.api.file_ingest_api as m

    mock_cfg = MagicMock()
    mock_cfg.rdb_dsn = "postgresql://x"
    mock_cfg.graph_url = "redis://x"
    mock_jobs = MagicMock()
    mock_datasource_store = MagicMock()

    with patch.object(m, "get_settings", return_value=mock_cfg), \
         patch.object(m, "JobStore", return_value=mock_jobs), \
         patch.object(m, "DatasourceStore", return_value=mock_datasource_store), \
         patch.object(m, "_local_broker", return_value=MagicMock()), \
         patch.object(m, "run_pipeline") as mock_run_pipeline, \
         patch.object(m, "upsert_xlsx_catalog_entry") as mock_upsert:
        m._run_files(
            items=[(two_sheet_xlsx_bytes, "Q3Export.xlsx")],
            ontology_type="Entity", match_keys=["name"], fk_links=[],
            job_id="job-1", workspace_id=1,
        )

    assert mock_run_pipeline.call_count == 2
    datasets = {call.kwargs["dataset"] for call in mock_run_pipeline.call_args_list}
    assert datasets == {"Q3Export__Customers", "Q3Export__Orders"}
    types = {call.kwargs["ontology_type"] for call in mock_run_pipeline.call_args_list}
    assert types == {"Customer", "Order"}  # sheet-derived, not the workbook name

    # Workbook traceability: the original bytes + both sheet assets are
    # recorded under the workbook's own filename.
    mock_upsert.assert_called_once()
    upsert_kwargs = mock_upsert.call_args.kwargs
    assert upsert_kwargs["source_filename"] == "Q3Export.xlsx"
    assert upsert_kwargs["xlsx_bytes"] == two_sheet_xlsx_bytes
    assert len(upsert_kwargs["assets"]) == 2


def test_run_files_xlsx_branch_auto_detects_cross_sheet_fk(monkeypatch):
    """Customers + Orders sharing a customer_id column must produce an
    auto-detected FK link, same as two related CSV files would."""
    import aryx.api.file_ingest_api as m

    data = _workbook_bytes({
        "Customers": [["customer_id", "name"], [1, "Acme"]],
        "Orders": [["order_id", "customer_id", "amount"], [100, 1, "50.00"]],
    })
    mock_cfg = MagicMock()
    mock_cfg.rdb_dsn = "postgresql://x"
    mock_cfg.graph_url = "redis://x"

    with patch.object(m, "get_settings", return_value=mock_cfg), \
         patch.object(m, "JobStore", return_value=MagicMock()), \
         patch.object(m, "DatasourceStore", return_value=MagicMock()), \
         patch.object(m, "_local_broker", return_value=MagicMock()), \
         patch.object(m, "run_pipeline") as mock_run_pipeline, \
         patch.object(m, "upsert_xlsx_catalog_entry"):
        m._run_files(
            items=[(data, "Sales.xlsx")],
            ontology_type="Entity", match_keys=["name"], fk_links=[],
            job_id="job-2", workspace_id=1,
        )

    # The LAST plan's call carries the auto-detected fk_links (mirrors the
    # XML path's relate-on-last-plan semantics).
    last_call = mock_run_pipeline.call_args_list[-1]
    assert last_call.kwargs["fk_links"], "expected an auto-detected FK link between Customers and Orders"
    assert last_call.kwargs["relate"] is True
    first_call = mock_run_pipeline.call_args_list[0]
    assert first_call.kwargs["relate"] is False
    assert first_call.kwargs["skip_graph"] is True


def test_run_files_xlsx_skips_hidden_sheet_end_to_end(monkeypatch):
    """A hidden sheet alongside a visible one must produce exactly one
    run_pipeline() call — the hidden sheet never reaches the pipeline at
    all. (A workbook can't have ALL sheets hidden — Excel itself forbids a
    workbook with zero visible sheets — so this is the real-world case.)"""
    import aryx.api.file_ingest_api as m

    data = _workbook_bytes(
        {"Visible": [["id"], [1]], "Secret": [["id"], [2]]},
        hidden={"Secret"},
    )
    mock_cfg = MagicMock()
    mock_cfg.rdb_dsn = "postgresql://x"
    mock_cfg.graph_url = "redis://x"

    with patch.object(m, "get_settings", return_value=mock_cfg), \
         patch.object(m, "JobStore", return_value=MagicMock()), \
         patch.object(m, "DatasourceStore", return_value=MagicMock()), \
         patch.object(m, "_local_broker", return_value=MagicMock()), \
         patch.object(m, "run_pipeline") as mock_run_pipeline, \
         patch.object(m, "upsert_xlsx_catalog_entry") as mock_upsert:
        m._run_files(
            items=[(data, "PartlyHidden.xlsx")],
            ontology_type="Entity", match_keys=["name"], fk_links=[],
            job_id="job-3", workspace_id=1,
        )

    mock_run_pipeline.assert_called_once()
    assert mock_run_pipeline.call_args.kwargs["dataset"] == "PartlyHidden__Visible"
    mock_upsert.assert_called_once()
    assert len(mock_upsert.call_args.kwargs["assets"]) == 1
