"""Tests for the Aryx <-> Shay bridge API."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from aryx.api.shay_bridge_api import shay_bridge_router

    app = FastAPI()
    app.include_router(shay_bridge_router())
    return TestClient(app, raise_server_exceptions=False)


def test_ensure_workspace_mapping_creates_aryx_workspace_when_missing(client):
    class FakeStore:
        def close(self):
            return None

        def ensure_workspace_mapping(self, **kwargs):
            assert kwargs["shay_workspace_id"] == "ws-1"
            assert kwargs["name"] == "Shay Alpha"
            return {
                "shay_workspace_id": "ws-1",
                "aryx_workspace_id": 7,
                "company_id": "co-1",
                "created": True,
            }

    with patch("aryx.api.shay_bridge_api.ShayBridgeStore", return_value=FakeStore()):
        resp = client.post(
            "/admin/shay/workspaces/ensure",
            json={
                "shay_workspace_id": "ws-1",
                "name": "Shay Alpha",
                "description": "demo",
                "company_id": "co-1",
            },
        )

    assert resp.status_code == 200
    assert resp.json()["aryx_workspace_id"] == 7
    assert resp.json()["created"] is True


def test_shay_chat_ask_uses_mapped_workspace_and_persists_turn(client):
    class FakeStore:
        def close(self):
            return None

        def ensure_chat_mapping(self, **kwargs):
            assert kwargs["shay_thread_id"] == "thread-1"
            assert kwargs["aryx_workspace_id"] == 9
            return {
                "shay_thread_id": "thread-1",
                "shay_workspace_id": "ws-9",
                "aryx_workspace_id": 9,
                "ask_session_key": "thread-1",
                "created": True,
            }

        def get_workspace_mapping(self, shay_workspace_id):
            assert shay_workspace_id == "ws-9"
            return {
                "shay_workspace_id": "ws-9",
                "aryx_workspace_id": 9,
                "company_id": "co-9",
            }

        def conversation_history(self, shay_thread_id, limit_pairs=6):
            assert shay_thread_id == "thread-1"
            assert limit_pairs == 6
            return [
                {"role": "user", "text": "Earlier question"},
                {"role": "assistant", "text": "Earlier answer"},
            ]

        def append_chat_turn(self, **kwargs):
            assert kwargs["shay_thread_id"] == "thread-1"
            assert kwargs["aryx_workspace_id"] == 9
            assert kwargs["question"] == "What changed?"
            assert kwargs["answer"] == "A mapped answer"
            return {"id": 1}

    fake_answer = {
        "answer": "A mapped answer",
        "terms": ["change"],
        "tools_called": [],
        "usage": {"latency_ms": 10, "answer_model": "test"},
        "grounding": {
            "citations": [{"entity_id": 1, "entity_name": "Acme", "entity_type": "Company"}],
        },
    }

    with (
        patch("aryx.api.shay_bridge_api.ShayBridgeStore", return_value=FakeStore()),
        patch("aryx.api.shay_bridge_api.run_ask", return_value=fake_answer),
    ):
        resp = client.post(
            "/admin/shay/chats/ask",
            json={
                "shay_workspace_id": "ws-9",
                "shay_thread_id": "thread-1",
                "question": "What changed?",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["aryx_workspace_id"] == 9
    assert data["answer"] == "A mapped answer"
    assert data["citations"][0]["entity_name"] == "Acme"


def test_shay_chat_history_returns_persisted_turns(client):
    class FakeStore:
        def close(self):
            return None

        def list_chat_turns(self, shay_thread_id, limit=50):
            assert shay_thread_id == "thread-77"
            assert limit == 25
            return [
                {
                    "id": 1,
                    "shay_thread_id": "thread-77",
                    "question": "Q1",
                    "answer": "A1",
                    "citations": [],
                },
            ]

    with patch("aryx.api.shay_bridge_api.ShayBridgeStore", return_value=FakeStore()):
        resp = client.get("/admin/shay/chats/history?shay_thread_id=thread-77&limit=25")

    assert resp.status_code == 200
    assert resp.json()[0]["question"] == "Q1"


def test_shay_chat_threads_returns_workspace_sessions(client):
    class FakeStore:
        def close(self):
            return None

        def list_workspace_threads(self, shay_workspace_id, limit=50):
            assert shay_workspace_id == "ws-77"
            assert limit == 10
            return [
                {
                    "shay_thread_id": "thread-abc",
                    "aryx_workspace_id": 3,
                    "ask_session_key": "thread-abc",
                    "updated_at": "2026-06-26T10:00:00Z",
                    "title": "First mapped prompt",
                    "turn_count": 4,
                },
            ]

    with patch("aryx.api.shay_bridge_api.ShayBridgeStore", return_value=FakeStore()):
        resp = client.get("/admin/shay/chats/threads?shay_workspace_id=ws-77&limit=10")

    assert resp.status_code == 200
    assert resp.json()[0]["shay_thread_id"] == "thread-abc"
