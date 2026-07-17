"""Regression tests for retrying failed Shay-backed Ask requests."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

SHAY_WORKSPACE_ID = "00000000-0000-0000-0000-000000000009"
THREAD_ID = "00000000-0000-0000-0000-000000000010"
REQUEST_ID = "00000000-0000-0000-0000-000000000001"


def _client() -> TestClient:
    from aryx.api.ask_thread_api import ask_thread_router
    from aryx.api.security import require_api_key

    app = FastAPI()
    app.include_router(ask_thread_router())
    app.dependency_overrides[require_api_key] = lambda: "test-key"
    return TestClient(app, raise_server_exceptions=False)


def _payload() -> dict[str, object]:
    return {
        "workspace_id": 7,
        "shay_workspace_id": SHAY_WORKSPACE_ID,
        "thread_id": THREAD_ID,
        "request_id": REQUEST_ID,
        "question": "What changed?",
    }


def test_ask_thread_submit_retries_cached_failure_instead_of_replaying_it():
    class FakeStore:
        def close(self):
            return None

        def validate_mapping(self, workspace_id, shay_workspace_id):
            return None

        def get_completed_response(self, shay_workspace_id, thread_id, request_id):
            return {
                "answer": "Aryx Ask could not complete this response. Please try again.",
                "error": "provider timeout",
                "terms": [],
                "tools_called": [],
                "usage": {},
                "session_data": {},
                "citations": [],
            }

        def ensure_thread_and_user_message(self, **kwargs):
            return {
                "thread_id": kwargs["thread_id"],
                "channel_id": "00000000-0000-0000-0000-000000000099",
                "user_message_id": "00000000-0000-0000-0000-000000000101",
                "request_claimed": True,
            }

        def conversation_history(self, thread_id, before_request_id, limit_pairs=6):
            return []

        def mark_request_completed(self, thread_id, request_id):
            return None

        def append_assistant_message(self, **kwargs):
            return {
                "assistant_message_id": "00000000-0000-0000-0000-000000000202",
                "citations": [],
            }

    with (
        patch("aryx.api.ask_thread_api.AryxAskThreadStore", return_value=FakeStore()),
        patch(
            "aryx.api.ask_thread_api.run_ask",
            return_value={"answer": "Retry succeeded", "session_data": {}},
        ) as run_ask_mock,
        patch("aryx.api.ask_thread_api._validate_workspace", return_value=None),
    ):
        resp = _client().post("/ask/threads/message", json=_payload())

    assert resp.status_code == 200
    assert resp.json()["answer"] == "Retry succeeded"
    run_ask_mock.assert_called_once()


def test_ask_thread_submit_releases_request_when_failure_response_persist_fails():
    releases: list[tuple[str, str]] = []

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
                "request_claimed": True,
            }

        def conversation_history(self, thread_id, before_request_id, limit_pairs=6):
            return []

        def append_assistant_message(self, **kwargs):
            raise RuntimeError("response write failed")

        def mark_request_retryable(self, thread_id, request_id):
            releases.append((thread_id, request_id))

    with (
        patch("aryx.api.ask_thread_api.AryxAskThreadStore", return_value=FakeStore()),
        patch("aryx.api.ask_thread_api.run_ask", side_effect=RuntimeError("provider timeout")),
        patch("aryx.api.ask_thread_api._validate_workspace", return_value=None),
    ):
        resp = _client().post("/ask/threads/message", json=_payload())

    assert resp.status_code == 502
    assert releases == [(THREAD_ID, REQUEST_ID)]


def test_ask_thread_submit_does_not_rerun_success_after_response_persist_fails():
    class FakeStore:
        def __init__(self):
            self.request_status = None

        def close(self):
            return None

        def validate_mapping(self, workspace_id, shay_workspace_id):
            return None

        def get_completed_response(self, shay_workspace_id, thread_id, request_id):
            return None

        def ensure_thread_and_user_message(self, **kwargs):
            request_claimed = self.request_status != "completed"
            if request_claimed:
                self.request_status = "in_progress"
            return {
                "thread_id": kwargs["thread_id"],
                "channel_id": "00000000-0000-0000-0000-000000000099",
                "user_message_id": "00000000-0000-0000-0000-000000000101",
                "request_claimed": request_claimed,
            }

        def conversation_history(self, thread_id, before_request_id, limit_pairs=6):
            return []

        def mark_request_completed(self, thread_id, request_id):
            self.request_status = "completed"

        def append_assistant_message(self, **kwargs):
            raise RuntimeError("response write failed")

        def mark_request_retryable(self, thread_id, request_id):
            self.request_status = "failed"

    store = FakeStore()
    with (
        patch("aryx.api.ask_thread_api.AryxAskThreadStore", return_value=store),
        patch(
            "aryx.api.ask_thread_api.run_ask",
            return_value={"answer": "Successful answer", "session_data": {}},
        ) as run_ask_mock,
        patch("aryx.api.ask_thread_api._validate_workspace", return_value=None),
    ):
        first_resp = _client().post("/ask/threads/message", json=_payload())
        retry_resp = _client().post("/ask/threads/message", json=_payload())

    assert (first_resp.status_code, retry_resp.status_code) == (200, 409)
    run_ask_mock.assert_called_once()
