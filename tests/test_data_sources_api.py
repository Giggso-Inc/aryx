"""Tests for XML-aware data source endpoints."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aryx.api.data_api import data_router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(data_router())
    return TestClient(app, raise_server_exceptions=False)


class _FakeDatasourceStore:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def list(self, workspace_id: int) -> list[dict]:
        return self.rows

    def get(self, datasource_id: int) -> dict | None:
        return next((row for row in self.rows if row["id"] == datasource_id), None)

    def add(self, workspace_id: int, name: str, kind: str, config: dict,
            secret: str) -> dict:
        row = {
            "id": len(self.rows) + 1,
            "workspace_id": workspace_id,
            "name": name,
            "kind": kind,
            "config": config,
            "secret_mask": "",
            "created_at": None,
        }
        self.rows.append(row)
        return row

    def update(self, datasource_id: int, *, name: str, kind: str,
               config: dict, secret: str | None = None) -> dict:
        row = self.get(datasource_id)
        assert row is not None
        row["name"] = name
        row["kind"] = kind
        row["config"] = config
        return row


class _FakeEntityStore:
    def __init__(
        self,
        provenance: list[tuple[int, str, str, str]],
        source_activity: dict[tuple[str, str], object] | None = None,
    ) -> None:
        self._provenance = provenance
        self._source_activity = source_activity or {}

    def list_members_provenance(self):
        return list(self._provenance)

    def list_source_payloads(self, source_system: str, source_dataset: str, *,
                              limit: int | None = None) -> list[dict]:
        rows: dict[str, list[dict]] = {
            "Corporate_Data_Employees": [
                {"employee_id": "1", "name": "Alice"},
                {"employee_id": "2", "name": "Bob"},
            ],
            "shipments": [
                {
                    "shipment_id": str(9000 + index),
                    "status": "Delayed" if index % 2 == 0 else "Pending Pickup",
                }
                for index in range(1, 31)
            ],
        }
        items = list(rows.get(source_dataset, []))
        if limit is None:
            return items
        return items[:limit]

    def list_source_activity(self) -> dict[tuple[str, str], object]:
        return dict(self._source_activity)

    def close(self) -> None:
        return None


class _FakeJobStore:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def list_recent(self, workspace_id: int = 1) -> list[dict]:
        return list(self.rows)

    def close(self) -> None:
        return None


def _xml_row() -> dict:
    return {
        "id": 9,
        "workspace_id": 1,
        "name": "Corporate_Data.xml",
        "kind": "xml",
        "config": {
            "source_catalog": {
                "xml": {
                    "source_filename": "Corporate_Data.xml",
                    "content_type": "application/xml",
                    "content_b64": "PHJvb3QvPg==",
                    "generated_assets": [
                        {
                            "asset_key": "Corporate_Data_Employees.csv",
                            "filename": "Corporate_Data_Employees.csv",
                            "dataset": "Corporate_Data_Employees",
                            "ontology_type": "Employee",
                            "content_b64": "YSxiCjEsMg==",
                            "content_type": "text/csv",
                        },
                    ],
                },
            },
        },
        "secret_mask": "",
        "created_at": None,
    }


def test_list_sources_returns_xml_parent_catalog_row(client: TestClient) -> None:
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=_FakeDatasourceStore([_xml_row()])),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([
            (1, "csv", "Corporate_Data_Employees", "1"),
        ])),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.get("/data/sources?workspace_id=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["name"] == "Corporate_Data.xml"
    assert payload[0]["isXmlParent"] is True


def test_get_xml_source_detail_returns_asset_list(client: TestClient) -> None:
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=_FakeDatasourceStore([_xml_row()])),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([
            (1, "csv", "Corporate_Data_Employees", "1"),
            (2, "csv", "Corporate_Data_Employees", "2"),
        ])),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.get("/data/sources/xml:9?workspace_id=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Corporate_Data.xml"
    assert payload["assets"][0]["record_count"] == 2
    assert payload["assets"][0]["preview_rows"][0]["name"] == "Alice"


def test_download_xml_source_returns_xml_bytes(client: TestClient) -> None:
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=_FakeDatasourceStore([_xml_row()])),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([])),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.get("/data/sources/xml:9/download?workspace_id=1")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert response.content == b"<root/>"


def test_source_preview_returns_all_rows_without_truncation(client: TestClient) -> None:
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=_FakeDatasourceStore([])),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([])),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.get("/data/sources/csv:shipments/preview?workspace_id=1")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["rows"]) == 30


def test_delete_generated_asset_marks_asset_deleted(client: TestClient) -> None:
    store = _FakeDatasourceStore([_xml_row()])
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=store),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([])),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.delete(
            "/data/sources/xml:9/assets/Corporate_Data_Employees.csv?workspace_id=1",
        )

    assert response.status_code == 200
    assets = store.rows[0]["config"]["source_catalog"]["xml"]["generated_assets"]
    assert assets[0]["deleted"] is True


def test_download_legacy_asset_builds_csv_from_landed_rows(client: TestClient) -> None:
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=_FakeDatasourceStore([])),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([
            (1, "csv", "Corporate_Data_Employees", "1"),
            (2, "csv", "Corporate_Data_Employees", "2"),
            (3, "csv", "Corporate_Data_Departments", "3"),
        ])),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.get(
            "/data/sources/legacy-xml:Corporate_Data/assets/Corporate_Data_Employees/download?workspace_id=1",
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert b"employee_id,name" in response.content


def test_download_generic_csv_source_builds_csv_from_landed_rows(client: TestClient) -> None:
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=_FakeDatasourceStore([])),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([
            (1, "csv", "orders", "1"),
        ])),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.get("/data/sources/csv:orders/download?workspace_id=1")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")


def test_delete_generic_csv_source_persists_hidden_catalog_row(client: TestClient) -> None:
    store = _FakeDatasourceStore([])
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=store),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore([
            (1, "csv", "orders", "1"),
        ])),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.delete("/data/sources/csv:orders?workspace_id=1")

    assert response.status_code == 200
    assert store.rows[0]["config"]["source_catalog"]["generic"]["is_active"] is False


def test_list_sources_revives_recently_reingested_generic_source(client: TestClient) -> None:
    store = _FakeDatasourceStore([
        {
            "id": 5,
            "workspace_id": 1,
            "name": "csv.suppliers",
            "kind": "source_catalog",
            "config": {
                "source_catalog": {
                    "generic": {
                        "source_system": "csv",
                        "source_dataset": "suppliers",
                        "is_active": False,
                        "deleted": True,
                    },
                },
            },
            "secret_mask": "",
            "created_at": None,
        },
    ])
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=store),
        patch("aryx.api.data_api.JobStore", return_value=_FakeJobStore([
            {
                "job_id": "job-1",
                "source_system": "upload",
                "source_dataset": "1 file(s)",
                "status": "complete",
                "detail": "Processing suppliers.csv",
                "updated_at": "2026-07-07T17:50:00+00:00",
                "finished_at": "2026-07-07T17:55:00+00:00",
            },
        ])),
        patch("aryx.api.data_api._store", return_value=_FakeEntityStore(
            [
                (1, "csv", "suppliers", "1"),
                (2, "csv", "suppliers", "2"),
            ],
            source_activity={
                ("csv", "suppliers"): "2026-07-07T17:56:00+00:00",
            },
        )),
        patch("aryx.api.data_api.get_settings") as mock_settings,
        patch("aryx.api.data_api.datetime") as mock_datetime,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        mock_datetime.now.return_value = __import__("datetime").datetime(2026, 7, 7, 18, 0, 0, tzinfo=__import__("datetime").timezone.utc)
        mock_datetime.fromisoformat.side_effect = __import__("datetime").datetime.fromisoformat
        response = client.get("/data/sources?workspace_id=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["name"] == "csv.suppliers"
    assert store.rows[0]["config"]["source_catalog"]["generic"]["is_active"] is True
