"""Contract tests for generic authenticated entity management endpoints."""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

for _module in ("falkordb", "psycopg", "psycopg.types", "psycopg.types.json", "psycopg_pool"):
    sys.modules.setdefault(_module, MagicMock())

from aryx.api.entity_management_api import entity_management_router
from aryx.api.security import require_api_key


class _Store:
    def __init__(self) -> None:
        self.created: tuple | None = None
        self.updated: tuple | None = None

    def get_entity(self, entity_id: int):
        if entity_id == 404:
            return None
        return (entity_id, "ManagedMaterial", {"Material": "Steel"}, 0.8,
                "created", "updated")

    def create_entity(self, ontology_type: str, attributes: dict, confidence: float):
        self.created = (ontology_type, attributes, confidence)
        return (25, ontology_type, attributes, confidence, "created", "created")

    def update_entity(self, entity_id: int, attributes: dict, confidence: float | None):
        if entity_id == 404:
            return None
        self.updated = (entity_id, attributes, confidence)
        return (entity_id, "ManagedMaterial", attributes,
                0.8 if confidence is None else confidence, "created", "updated")

    def close(self) -> None:
        pass


def _client(monkeypatch, enabled_workspaces: str = "51") -> tuple[TestClient, _Store]:
    store = _Store()
    settings = SimpleNamespace(
        entity_management_allowed_workspace_ids=enabled_workspaces,
        rdb_dsn="postgresql://unused",
        graph_url="redis://unused",
    )
    monkeypatch.setattr(
        "aryx.api.entity_management_api.get_settings", lambda: settings)
    monkeypatch.setattr(
        "aryx.api.entity_management_api._store", lambda _: store)
    monkeypatch.setattr(
        "aryx.api.entity_management_api._reproject", lambda _: {"entities": 1})
    app = FastAPI()
    app.include_router(entity_management_router())
    app.dependency_overrides[require_api_key] = lambda: "test-key"
    return TestClient(app), store


def test_entity_management_reads_one_entity(monkeypatch) -> None:
    client, _ = _client(monkeypatch)

    response = client.get("/admin/entities/25?workspace_id=51")

    assert response.status_code == 200
    assert response.json()["ontology_type"] == "ManagedMaterial"


def test_entity_management_creates_and_projects_entity(monkeypatch) -> None:
    client, store = _client(monkeypatch)

    response = client.post("/admin/entities", json={
        "workspace_id": 51,
        "ontology_type": "ManagedMaterial",
        "attributes": {"Material": "Steel", "Active": True},
        "confidence": 0.9,
    })

    assert response.status_code == 201
    assert store.created == (
        "ManagedMaterial", {"Material": "Steel", "Active": True}, 0.9)
    assert response.json()["projected"]["entities"] == 1


def test_entity_management_updates_and_projects_entity(monkeypatch) -> None:
    client, store = _client(monkeypatch)

    response = client.put("/admin/entities/25?workspace_id=51", json={
        "attributes": {"Material": "Steel", "Active": False},
    })

    assert response.status_code == 200
    assert store.updated == (25, {"Material": "Steel", "Active": False}, None)
    assert response.json()["attributes"]["Active"] is False


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/admin/entities/25?workspace_id=52", None),
        ("POST", "/admin/entities", {
            "workspace_id": 52,
            "ontology_type": "ManagedMaterial",
            "attributes": {"Material": "Steel"},
        }),
        ("PUT", "/admin/entities/25?workspace_id=52", {
            "attributes": {"Material": "Steel", "Active": False},
        }),
    ],
)
def test_entity_management_rejects_every_operation_for_unconfigured_workspace(
    monkeypatch,
    method: str,
    path: str,
    body: dict | None,
) -> None:
    client, _ = _client(monkeypatch, enabled_workspaces="51")

    response = client.request(method, path, json=body)

    assert response.status_code == 403


def test_entity_management_allows_any_workspace_without_a_configured_restriction(monkeypatch) -> None:
    client, store = _client(monkeypatch, enabled_workspaces="")

    response = client.post("/admin/entities", json={
        "workspace_id": 52,
        "ontology_type": "ManagedMaterial",
        "attributes": {"Material": "Steel"},
    })

    assert response.status_code == 201
    assert store.created is not None
