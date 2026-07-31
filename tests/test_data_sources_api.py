"""Tests for XML-aware data source endpoints."""
from __future__ import annotations

import sys
import types
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient


def _stub_import_only_dependencies() -> None:
    if "falkordb" not in sys.modules:
        falkordb = types.ModuleType("falkordb")
        falkordb.FalkorDB = object
        sys.modules["falkordb"] = falkordb
    if "raven_logger" not in sys.modules:
        raven_logger = types.ModuleType("raven_logger")
        raven_logger.new_span_id = lambda: "span-test"
        raven_logger.new_trace_id = lambda: "trace-test"
        raven_logger.raven_log = lambda **kwargs: kwargs
        sys.modules["raven_logger"] = raven_logger
    if "cryptography.fernet" not in sys.modules:
        cryptography = types.ModuleType("cryptography")
        fernet = types.ModuleType("cryptography.fernet")

        class _Fernet:
            def __init__(self, _key: bytes) -> None:
                pass

            def encrypt(self, value: bytes) -> bytes:
                return value

            def decrypt(self, value: bytes) -> bytes:
                return value

        class _InvalidToken(Exception):
            pass

        fernet.Fernet = _Fernet
        fernet.InvalidToken = _InvalidToken
        cryptography.fernet = fernet
        sys.modules["cryptography"] = cryptography
        sys.modules["cryptography.fernet"] = fernet


_stub_import_only_dependencies()

from aryx.api.data_api import _purge_relational_source, data_router
from aryx.store.entity_store import EntityStore
from aryx.store.source_purge_store import SourcePurgeBusy


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(data_router())
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def no_active_ingestion_jobs():
    with patch(
        "aryx.api.data_api.JobStore",
        return_value=_FakeJobStore([]),
    ):
        yield


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

    def delete(self, datasource_id: int) -> None:
        self.rows[:] = [row for row in self.rows if row["id"] != datasource_id]


class _FakeEntityStore:
    def __init__(
        self,
        provenance: list[tuple[int, str, str, str]],
        source_activity: dict[tuple[str, str], object] | None = None,
    ) -> None:
        self._provenance = provenance
        self._source_activity = source_activity or {}
        self.purged_refs: list[tuple[str, str]] = []

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
            "orders": [{"order_id": "1", "status": "Ready"}],
        }
        items = list(rows.get(source_dataset, []))
        if limit is None:
            return items
        return items[:limit]

    def list_source_activity(self) -> dict[tuple[str, str], object]:
        return dict(self._source_activity)

    def list_entities(self):
        return []

    def list_relationships(self):
        return []

    def purge_source_references(
        self,
        refs: list[tuple[str, str]] | tuple[tuple[str, str], ...],
    ) -> dict:
        self.purged_refs.extend(list(refs))
        return {
            "sources_purged": len(refs),
            "landed_records_deleted": 2,
            "members_deleted": 2,
            "entities_impacted": 2,
            "entities_deleted": 2,
            "entity_ids_deleted": [101, 102],
        }

    def close(self) -> None:
        return None


class _FakeJobStore:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def list_recent(self, workspace_id: int = 1) -> list[dict]:
        return list(self.rows)

    def close(self) -> None:
        return None


class _FailingGraphStore:
    def clear(self) -> None:
        raise RuntimeError("graph unavailable")


class _WorkingGraphStore:
    def clear(self) -> None:
        return None

    def add_entity(self, *_args, **_kwargs) -> None:
        return None

    def add_provenance(self, *_args, **_kwargs) -> None:
        return None

    def add_relationship(self, *_args, **_kwargs) -> None:
        return None


class _FakeSourcePurgeStore:
    def __init__(self, result: dict | None = None, error: Exception | None = None) -> None:
        self.result = result or {"sources_purged": 1}
        self.error = error
        self.calls: list[tuple[object, object, object]] = []

    def purge(
        self,
        refs: list[tuple[str, str]],
        *,
        catalog_delete_ids: list[int],
        catalog_update: object = None,
    ) -> dict:
        self.calls.append((refs, catalog_delete_ids, catalog_update))
        if self.error is not None:
            raise self.error
        return self.result


def _real_entity_store_stub() -> EntityStore:
    return object.__new__(EntityStore)


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


def test_delete_generated_asset_purges_asset_dataset(client: TestClient) -> None:
    store = _FakeDatasourceStore([_xml_row()])
    entity_store = _FakeEntityStore([])
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=store),
        patch("aryx.api.data_api._store", return_value=entity_store),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.delete(
            "/data/sources/xml:9/assets/Corporate_Data_Employees.csv?workspace_id=1",
        )

    assert response.status_code == 200
    assert entity_store.purged_refs == [("csv", "Corporate_Data_Employees")]
    assert store.rows == []
    assert response.json()["catalog_rows_deleted"] == 1


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


def test_delete_generic_csv_source_purges_source_records(client: TestClient) -> None:
    store = _FakeDatasourceStore([])
    entity_store = _FakeEntityStore([
        (1, "csv", "orders", "1"),
    ])
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=store),
        patch("aryx.api.data_api._store", return_value=entity_store),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.delete("/data/sources/csv:orders?workspace_id=1")

    assert response.status_code == 200
    assert entity_store.purged_refs == [("csv", "orders")]
    assert response.json()["landed_records_deleted"] == 2


def test_purge_relational_source_uses_atomic_store_for_real_entity_store() -> None:
    purge_store = _FakeSourcePurgeStore({"sources_purged": 1, "runs_deleted": 2})
    with patch("aryx.api.data_api._source_purge_store", return_value=purge_store):
        result = _purge_relational_source(
            _real_entity_store_stub(),
            _FakeDatasourceStore([]),
            1,
            [("csv", "orders")],
            catalog_delete_ids=[9],
        )

    assert result["runs_deleted"] == 2
    assert purge_store.calls == [([("csv", "orders")], [9], None)]


def test_purge_relational_source_maps_busy_to_409() -> None:
    purge_store = _FakeSourcePurgeStore(error=SourcePurgeBusy("job-1"))
    with patch("aryx.api.data_api._source_purge_store", return_value=purge_store):
        with pytest.raises(HTTPException) as exc_info:
            _purge_relational_source(
                _real_entity_store_stub(),
                _FakeDatasourceStore([]),
                1,
                [("csv", "orders")],
                catalog_delete_ids=[],
            )

    assert exc_info.value.status_code == 409


def test_purge_relational_source_maps_missing_workspace_to_404() -> None:
    purge_store = _FakeSourcePurgeStore(error=ValueError("workspace 99 not found"))
    with patch("aryx.api.data_api._source_purge_store", return_value=purge_store):
        with pytest.raises(HTTPException) as exc_info:
            _purge_relational_source(
                _real_entity_store_stub(),
                _FakeDatasourceStore([]),
                99,
                [("csv", "orders")],
                catalog_delete_ids=[],
            )

    assert exc_info.value.status_code == 404


def test_delete_source_is_blocked_while_ingestion_is_active(
    client: TestClient,
) -> None:
    entity_store = _FakeEntityStore([(1, "csv", "orders", "1")])
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=_FakeDatasourceStore([])),
        patch("aryx.api.data_api.JobStore", return_value=_FakeJobStore([
            {"job_id": "job-1", "status": "running"},
        ])),
        patch("aryx.api.data_api._store", return_value=entity_store),
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        response = client.delete("/data/sources/csv:orders?workspace_id=1")

    assert response.status_code == 409
    assert entity_store.purged_refs == []
    assert "ingestion" in response.json()["detail"].lower()


def test_delete_reports_graph_repair_requirement(
    client: TestClient,
) -> None:
    entity_store = _FakeEntityStore([(1, "csv", "orders", "1")])
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=_FakeDatasourceStore([])),
        patch("aryx.api.data_api.JobStore", return_value=_FakeJobStore([])),
        patch("aryx.api.data_api._store", return_value=entity_store),
        patch("aryx.api.data_api.ports") as mock_ports,
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        mock_ports.return_value.graph_store.return_value = _FailingGraphStore()
        response = client.delete("/data/sources/csv:orders?workspace_id=1")

    assert response.status_code == 200
    assert response.json()["graph_sync"] == "repair_required"


def test_delete_supports_graph_adapter_without_remove_source(
    client: TestClient,
) -> None:
    entity_store = _FakeEntityStore([(1, "csv", "orders", "1")])
    with (
        patch("aryx.api.data_api.DatasourceStore", return_value=_FakeDatasourceStore([])),
        patch("aryx.api.data_api._store", return_value=entity_store),
        patch("aryx.api.data_api.ports") as mock_ports,
        patch("aryx.api.data_api.get_settings") as mock_settings,
    ):
        mock_settings.return_value.rdb_dsn = "postgresql://test"
        mock_ports.return_value.graph_store.return_value = _WorkingGraphStore()
        response = client.delete("/data/sources/csv:orders?workspace_id=1")

    assert response.status_code == 200
    assert response.json()["graph_sync"] == "complete"


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
