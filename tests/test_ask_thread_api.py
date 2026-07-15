"""Tests for the Shay-message-backed Aryx Ask thread API."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client() -> TestClient:
    from aryx.api.ask_thread_api import ask_thread_router
    from aryx.api.security import require_api_key

    app = FastAPI()
    app.include_router(ask_thread_router())
    app.dependency_overrides[require_api_key] = lambda: "test-key"
    return TestClient(app, raise_server_exceptions=False)


def test_ask_thread_submit_persists_prompt_before_running_ask():
    events: list[str] = []

    class FakeStore:
        def close(self):
            return None

        def validate_mapping(self, workspace_id, shay_workspace_id):
            assert workspace_id == 7

        def get_completed_response(self, shay_workspace_id, thread_id, request_id):
            events.append("cached-check")
            return None

        def ensure_thread_and_user_message(self, **kwargs):
            events.append("user-message")
            assert kwargs["workspace_id"] == 7
            assert kwargs["shay_workspace_id"] == "00000000-0000-0000-0000-000000000009"
            assert kwargs["question"] == "What changed?"
            return {
                "thread_id": kwargs["thread_id"],
                "channel_id": "00000000-0000-0000-0000-000000000099",
                "created_thread": True,
                "user_message_id": "00000000-0000-0000-0000-000000000101",
            }

        def conversation_history(self, thread_id, before_request_id, limit_pairs=6):
            events.append("history")
            assert before_request_id == "00000000-0000-0000-0000-000000000001"
            return [{"role": "user", "text": "Earlier"}]

        def append_assistant_message(self, **kwargs):
            events.append("assistant-message")
            assert kwargs["answer"] == "Mapped answer"
            return {"assistant_message_id": "00000000-0000-0000-0000-000000000202"}

    def fake_run_ask(req):
        events.append("llm")
        assert req.history[0].text == "Earlier"
        return {
            "answer": "Mapped answer",
            "terms": ["change"],
            "tools_called": [],
            "usage": {"latency_ms": 10, "answer_model": "test"},
            "grounding": None,
            "session_data": {"mode": "cpq"},
        }

    with (
        patch("aryx.api.ask_thread_api.AryxAskThreadStore", return_value=FakeStore()),
        patch("aryx.api.ask_thread_api.run_ask", side_effect=fake_run_ask),
        patch("aryx.api.ask_thread_api._validate_workspace", return_value=None),
    ):
        resp = _client().post(
            "/ask/threads/message",
            json={
                "workspace_id": 7,
                "shay_workspace_id": "00000000-0000-0000-0000-000000000009",
                "thread_id": "00000000-0000-0000-0000-000000000010",
                "request_id": "00000000-0000-0000-0000-000000000001",
                "question": "What changed?",
                "session_data": {},
            },
        )

    assert resp.status_code == 200
    assert resp.json()["answer"] == "Mapped answer"
    assert events == ["cached-check", "user-message", "history", "llm", "assistant-message"]


def test_ask_thread_submit_returns_cached_answer_without_running_ask():
    class FakeStore:
        def close(self):
            return None

        def validate_mapping(self, workspace_id, shay_workspace_id):
            return None

        def get_completed_response(self, shay_workspace_id, thread_id, request_id):
            return {
                "answer": "Cached answer",
                "terms": ["cached"],
                "tools_called": [],
                "usage": {"latency_ms": 1},
                "session_data": {},
                "citations": [],
            }

    with (
        patch("aryx.api.ask_thread_api.AryxAskThreadStore", return_value=FakeStore()),
        patch("aryx.api.ask_thread_api.run_ask") as run_ask_mock,
        patch("aryx.api.ask_thread_api._validate_workspace", return_value=None),
    ):
        resp = _client().post(
            "/ask/threads/message",
            json={
                "workspace_id": 7,
                "shay_workspace_id": "00000000-0000-0000-0000-000000000009",
                "thread_id": "00000000-0000-0000-0000-000000000010",
                "request_id": "00000000-0000-0000-0000-000000000001",
                "question": "What changed?",
            },
        )

    assert resp.status_code == 200
    assert resp.json()["replayed"] is True
    run_ask_mock.assert_not_called()


def test_ask_thread_submit_does_not_run_ask_when_request_is_in_progress():
    class FakeStore:
        def close(self):
            return None

        def validate_mapping(self, workspace_id, shay_workspace_id):
            return None

        def get_completed_response(self, shay_workspace_id, thread_id, request_id):
            return None

        def ensure_thread_and_user_message(self, **kwargs):
            return {
                "thread_id": kwargs["thread_id"],
                "channel_id": "00000000-0000-0000-0000-000000000099",
                "user_message_id": "00000000-0000-0000-0000-000000000101",
                "request_claimed": False,
            }

    with (
        patch("aryx.api.ask_thread_api.AryxAskThreadStore", return_value=FakeStore()),
        patch("aryx.api.ask_thread_api.run_ask") as run_ask_mock,
        patch("aryx.api.ask_thread_api._validate_workspace", return_value=None),
    ):
        resp = _client().post(
            "/ask/threads/message",
            json={
                "workspace_id": 7,
                "shay_workspace_id": "00000000-0000-0000-0000-000000000009",
                "thread_id": "00000000-0000-0000-0000-000000000010",
                "request_id": "00000000-0000-0000-0000-000000000001",
                "question": "What changed?",
            },
        )

    assert resp.status_code == 409
    run_ask_mock.assert_not_called()


def test_ask_thread_submit_does_not_run_ask_when_prompt_persist_fails():
    class FakeStore:
        def close(self):
            return None

        def validate_mapping(self, workspace_id, shay_workspace_id):
            return None

        def get_completed_response(self, shay_workspace_id, thread_id, request_id):
            return None

        def ensure_thread_and_user_message(self, **kwargs):
            raise RuntimeError("database unavailable")

    with (
        patch("aryx.api.ask_thread_api.AryxAskThreadStore", return_value=FakeStore()),
        patch("aryx.api.ask_thread_api.run_ask") as run_ask_mock,
        patch("aryx.api.ask_thread_api._validate_workspace", return_value=None),
    ):
        resp = _client().post(
            "/ask/threads/message",
            json={
                "workspace_id": 7,
                "shay_workspace_id": "00000000-0000-0000-0000-000000000009",
                "thread_id": "00000000-0000-0000-0000-000000000010",
                "request_id": "00000000-0000-0000-0000-000000000001",
                "question": "What changed?",
            },
        )

    assert resp.status_code == 503
    run_ask_mock.assert_not_called()


def test_ask_threads_and_messages_are_read_only():
    class FakeStore:
        def close(self):
            return None

        def list_threads(self, workspace_id, shay_workspace_id, limit=50):
            return [{"id": "thread-1", "title": "First prompt", "message_count": 2}]

        def list_messages(self, workspace_id, shay_workspace_id, thread_id, before_sequence=None, limit=50):
            assert workspace_id == 7
            assert shay_workspace_id == "00000000-0000-0000-0000-000000000009"
            return [{"id": "msg-1", "role": "user", "content": "First prompt"}]

    with (
        patch("aryx.api.ask_thread_api.AryxAskThreadStore", return_value=FakeStore()),
        patch("aryx.api.ask_thread_api.run_ask") as run_ask_mock,
        patch("aryx.api.ask_thread_api._validate_workspace", return_value=None),
    ):
        threads = _client().get(
            "/ask/threads?workspace_id=7&shay_workspace_id=00000000-0000-0000-0000-000000000009"
        )
        messages = _client().get(
            "/ask/threads/thread-1/messages?workspace_id=7&shay_workspace_id=00000000-0000-0000-0000-000000000009&limit=25"
        )

    assert threads.status_code == 200
    assert threads.json()[0]["title"] == "First prompt"
    assert messages.status_code == 200
    assert messages.json()[0]["role"] == "user"
    run_ask_mock.assert_not_called()


def test_normalize_grounding_citations_maps_backend_shape_to_ui_shape():
    from aryx.store.ask_thread_store import normalize_grounding_citations

    citations = normalize_grounding_citations({
        "citations": [
            {
                "marker": 1,
                "entity_id": "42",
                "entity_name": "Acme Corp",
                "entity_type": "Customer",
                "system": "crm",
            }
        ]
    })

    assert citations == [
        {"entity_id": 42, "label": "Acme Corp", "type": "Customer"}
    ]
