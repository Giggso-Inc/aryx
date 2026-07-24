"""Tests for Excel-workbook-aware data source endpoints.

Raven review finding fixed here: upsert_xlsx_catalog_entry() (the write
side) worked correctly, but build_source_catalog()/build_source_detail()
and the delete-marking functions only ever recognized XML rows (_xml_meta
only) — an xlsx catalog row fell through to the generic/ungrouped branch,
and each per-sheet CSV dataset (e.g. "csv.Customers", "csv.Orders") was
never added to hidden_datasets/covered_keys, so they'd show up as
separate, ungrouped top-level rows in the Data tab instead of being
grouped under the parent workbook — exactly the multi-sheet grouping the
PR's description promised but never wired into the read/display path.

These tests mirror test_data_sources_api.py's existing XML test pattern
exactly, with an xlsx row instead, to prove parity.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aryx.api.data_api import data_router
from tests.test_data_sources_api import _FakeDatasourceStore, _FakeEntityStore


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(data_router())
    return TestClient(app, raise_server_exceptions=False)


def _xlsx_row() -> dict:
    return {
        "id": 42,
        "workspace_id": 1,
        "name": "Q3_Customer_Orders.xlsx",
        "kind": "xlsx",
        "config": {
            "source_catalog": {
                "xlsx": {
                    "source_filename": "Q3_Customer_Orders.xlsx",
                    "content_type": (
                        "application/vnd.openxmlformats-officedocument"
                        ".spreadsheetml.sheet"
                    ),
                    "content_b64": "UEsDBAoAAAAAAA==",  # arbitrary bytes, never parsed as real xlsx
                    "generated_assets": [
                        {
                            "asset_key": "Q3_Customer_Orders__Customers.csv",
                            "filename": "Q3_Customer_Orders__Customers.csv",
                            "dataset": "Q3_Customer_Orders__Customers",
                            "ontology_type": "Customer",
                            "content_b64": "bmFtZQpBY21l",  # "name\nAcme"
                            "content_type": "text/csv",
                        },
                        {
                            "asset_key": "Q3_Customer_Orders__Orders.csv",
                            "filename": "Q3_Customer_Orders__Orders.csv",
                            "dataset": "Q3_Customer_Orders__Orders",
                            "ontology_type": "Order",
                            "content_b64": "b3JkZXJfaWQKMTAwMQ==",  # "order_id\n1001"
                            "content_type": "text/csv",
                        },
                    ],
                },
            },
        },
        "secret_mask": "",
        "created_at": None,
    }


def test_list_sources_returns_grouped_xlsx_parent_row_not_ungrouped_sheets(client: TestClient) -> None:
    """The exact bug the Raven review flagged: per-sheet datasets must be
    HIDDEN under the parent workbook row, not shown as separate top-level
    sources."""
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=_FakeDatasourceStore([_xlsx_row()])),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([
            (1, "csv", "Q3_Customer_Orders__Customers", "1"),
            (2, "csv", "Q3_Customer_Orders__Orders", "2"),
        ])),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.get("/data/sources?workspace_id=1")

    assert response.status_code == 200
    payload = response.json()

    # Exactly one row: the grouped workbook parent. No ungrouped sheet rows.
    assert len(payload) == 1
    assert payload[0]["name"] == "Q3_Customer_Orders.xlsx"
    assert payload[0]["kind"] == "xlsx"
    assert payload[0]["display_kind"] == "Excel Workbook"
    assert payload[0]["isXmlParent"] is True
    assert payload[0]["generatedAssetCount"] == 2
    # Sheet-level record counts are summed onto the parent row.
    assert payload[0]["record_count"] == 2

    names = {row["name"] for row in payload}
    assert "csv.Q3_Customer_Orders__Customers" not in names
    assert "csv.Q3_Customer_Orders__Orders" not in names


def test_get_xlsx_source_detail_returns_both_sheet_assets(client: TestClient) -> None:
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=_FakeDatasourceStore([_xlsx_row()])),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([
            (1, "csv", "Q3_Customer_Orders__Customers", "1"),
            (2, "csv", "Q3_Customer_Orders__Customers", "2"),
        ])),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.get("/data/sources/xlsx:42?workspace_id=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Q3_Customer_Orders.xlsx"
    assert payload["generatedAssetCount"] == 2
    datasets = {a["dataset"] for a in payload["assets"]}
    assert datasets == {"Q3_Customer_Orders__Customers", "Q3_Customer_Orders__Orders"}
    customers_asset = next(a for a in payload["assets"] if a["dataset"] == "Q3_Customer_Orders__Customers")
    assert customers_asset["ontology_type"] == "Customer"
    assert customers_asset["record_count"] == 2


def test_download_xlsx_source_returns_workbook_bytes(client: TestClient) -> None:
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=_FakeDatasourceStore([_xlsx_row()])),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([])),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.get("/data/sources/xlsx:42/download?workspace_id=1")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "Q3_Customer_Orders.xlsx" in response.headers["content-disposition"]


def test_download_xlsx_sheet_asset_returns_csv_bytes(client: TestClient) -> None:
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=_FakeDatasourceStore([_xlsx_row()])),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([])),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.get(
            "/data/sources/xlsx:42/assets/Q3_Customer_Orders__Customers.csv/download?workspace_id=1",
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.content == b"name\nAcme"


def test_delete_xlsx_source_marks_workbook_and_all_assets_deleted(client: TestClient) -> None:
    store = _FakeDatasourceStore([_xlsx_row()])
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=store),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([])),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.delete("/data/sources/xlsx:42?workspace_id=1")

    assert response.status_code == 200
    meta = store.rows[0]["config"]["source_catalog"]["xlsx"]
    assert meta["deleted"] is True
    assert all(asset["deleted"] is True for asset in meta["generated_assets"])


def test_delete_xlsx_sheet_asset_marks_only_that_asset_deleted(client: TestClient) -> None:
    store = _FakeDatasourceStore([_xlsx_row()])
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=store),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([])),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.delete(
            "/data/sources/xlsx:42/assets/Q3_Customer_Orders__Customers.csv?workspace_id=1",
        )

    assert response.status_code == 200
    assets = store.rows[0]["config"]["source_catalog"]["xlsx"]["generated_assets"]
    deleted = {a["asset_key"]: a.get("deleted", False) for a in assets}
    assert deleted["Q3_Customer_Orders__Customers.csv"] is True
    assert deleted["Q3_Customer_Orders__Orders.csv"] is False


def test_xlsx_and_xml_rows_coexist_without_cross_contamination(client: TestClient) -> None:
    """A workspace with BOTH an XML upload and an xlsx upload must group
    each independently — proves _xml_meta/_xlsx_meta don't leak into each
    other's branch."""
    from tests.test_data_sources_api import _xml_row

    with (
        patch("aryx.api.data_api.DatasourceStore",
              return_value=_FakeDatasourceStore([_xml_row(), _xlsx_row()])),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([
            (1, "csv", "Corporate_Data_Employees", "1"),
            (2, "csv", "Q3_Customer_Orders__Customers", "2"),
        ])),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.get("/data/sources?workspace_id=1")

    assert response.status_code == 200
    payload = response.json()
    kinds = sorted(row["kind"] for row in payload)
    assert kinds == ["xlsx", "xml"]
