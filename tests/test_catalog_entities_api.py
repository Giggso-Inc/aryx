"""Contract tests for the generic catalog snapshot endpoint."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

for _module in ("psycopg", "psycopg.types", "psycopg.types.json", "psycopg_pool"):
    sys.modules.setdefault(_module, MagicMock())

from aryx.api.data_api import data_router
from aryx.api.security import require_api_key


class _Store:
    def __init__(self) -> None:
        self.count_args: list[str] | None = None

    def count_catalog_entities(self, types: list[str]) -> int:
        self.count_args = types
        return 2

    def list_catalog_entities(self, types: list[str], *, include_sources: bool):
        assert include_sources is True
        rows = [
            (10, "Material", {"material": "Steel"}),
            (11, "NoBid", {"NIIN": "014327514"}),
        ]
        return [row for row in rows if row[1] in types], [
            (10, "DLA", "critical_materials", "row-1")
        ]

    def close(self) -> None:
        pass


def _client(monkeypatch, enabled_workspaces: str = "51") -> TestClient:
    settings = MagicMock(
        catalog_allowed_workspace_ids=enabled_workspaces,
        catalog_max_entities=25_000,
    )
    monkeypatch.setattr("aryx.api.data_api.get_settings", lambda: settings)
    monkeypatch.setattr("aryx.api.data_api._store", lambda _: _Store())
    app = FastAPI()
    app.include_router(data_router())
    app.dependency_overrides[require_api_key] = lambda: "test-key"
    return TestClient(app)


def test_catalog_snapshot_is_typed_provenanced_and_stable(monkeypatch) -> None:
    client = _client(monkeypatch)
    url = "/data/catalog-entities?workspace_id=51&types=NoBid&types=Material"

    first = client.get(url)
    second = client.get(url)

    assert first.status_code == 200
    assert first.json()["types"] == ["Material", "NoBid"]
    assert first.json()["items"][0]["sources"][0]["dataset"] == "critical_materials"
    assert first.json()["revision"] == second.json()["revision"]


def test_catalog_snapshot_rejects_an_unconfigured_workspace(monkeypatch) -> None:
    client = _client(monkeypatch, enabled_workspaces="51")

    response = client.get("/data/catalog-entities?workspace_id=52&types=Material")

    assert response.status_code == 403


def test_catalog_snapshot_allows_any_workspace_without_a_configured_restriction(monkeypatch) -> None:
    client = _client(monkeypatch, enabled_workspaces="")

    response = client.get("/data/catalog-entities?workspace_id=52&types=Material")

    assert response.status_code == 200
