"""
Golden-master / characterization tests for app/routes/agent (package).

Purpose: agent.py was 370 lines with 5 HTTP endpoints (POST /callback,
POST /status, GET /health, GET /stats, POST /trigger/{message_id}) plus one
background-task helper (process_ai_request) and had ZERO test coverage
before this file (confirmed via grep across tests/ for "app.routes.agent").
It has been split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5):
  app/routes/agent/__init__.py           (router assembly)
  app/routes/agent/callback.py           (POST /callback)
  app/routes/agent/status.py             (POST /status)
  app/routes/agent/health.py             (GET /health)
  app/routes/agent/stats.py              (GET /stats)
  app/routes/agent/trigger.py            (POST /trigger/{message_id})
  app/routes/agent/process_ai_request.py (background-task helper, used only
                                           by trigger.py)

`process_ai_request` is imported into trigger.py's own namespace, so its
patch target is "app.routes.agent.trigger.process_ai_request", not
"app.routes.agent.process_ai_request".

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included. Notable PRE-EXISTING bugs
documented here (not fixed):

1. NO AUTHENTICATION on any endpoint in this router. Unlike almost every
   other router in app/routes/, agent.py never calls
   `get_current_user_required`. Any caller can POST a fake AI callback,
   flip an AI response's status, or trigger AI processing for an arbitrary
   message_id. This looks like it's intended to be a webhook receiver
   (external AI service -> our API) but has no shared-secret/HMAC check
   either.
2. Every endpoint body is wrapped in `try: ... except Exception as e: raise
   HTTPException(500, ...)`. Because FastAPI's `HTTPException` **is** an
   `Exception` subclass, any `HTTPException` deliberately raised *inside*
   the try block (the 404 "Message not found", 404 "AI response not
   found", and 400 "AI processing already triggered" cases) is itself
   caught by the blanket `except Exception`, and gets re-wrapped into a
   generic 500 with a detail string like
   "Failed to process AI callback: 404: Message not found" instead of
   propagating as the intended 404/400. This file asserts the ACTUAL
   status code (500) for those paths, not the apparently-intended one.

Pattern follows tests/test_audit_characterization.py /
tests/test_checklists_characterization.py:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for the DB session; no real DB, no real HTTP.
- No auth patching needed/possible here — there is no auth dependency.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.agent import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/agent")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _mock_db():
    """AsyncMock DB session with `.add` as a plain (sync) MagicMock, matching
    the real AsyncSession.add signature (it is not a coroutine)."""
    db = AsyncMock()
    db.add = MagicMock()
    return db


def _exec_result(scalar_one_or_none=None, scalar_val=None, all_=None):
    m = MagicMock()
    m.scalar_one_or_none = MagicMock(return_value=scalar_one_or_none)
    m.scalar = MagicMock(return_value=scalar_val)
    m.__iter__ = MagicMock(return_value=iter(all_ if all_ is not None else []))
    return m


def _exec_seq(*results):
    return AsyncMock(side_effect=list(results))


def _mock_message(message_id="msg-1", thread_id="thread-1", workspace_id="ws-1"):
    m = MagicMock()
    m.id = message_id
    m.thread_id = thread_id
    m.workspace_id = workspace_id
    m.content = "hello world " * 10
    return m


def _mock_ai_response(message_id="msg-1", retry_count=0):
    r = MagicMock()
    r.message_id = message_id
    r.retry_count = retry_count
    r.status = "pending"
    r.error_message = None
    r.ai_provider = "openai"
    r.ai_model = "gpt-4"
    r.processing_time_ms = None
    return r


CALLBACK_PAYLOAD = {
    "message_id": "msg-1",
    "thread_id": "thread-1",
    "workspace_id": "ws-1",
    "ai_provider": "openai",
    "ai_model": "gpt-4",
    "response_content": "the answer",
}


# ---------------------------------------------------------------------------
# POST /callback -> ai_callback
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_ai_callback_happy_path_creates_new_response():
    message = _mock_message()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_one_or_none=message),  # message lookup
        _exec_result(scalar_one_or_none=None),  # no existing ai_response
    )
    client = _make_client(mock_db)
    resp = client.post("/api/v1/agent/callback", json=CALLBACK_PAYLOAD)
    assert resp.status_code == 200
    assert resp.json() == {"message": "AI callback processed successfully"}
    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.unit
def test_ai_callback_happy_path_updates_existing_response():
    message = _mock_message()
    existing = _mock_ai_response()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_one_or_none=message),
        _exec_result(scalar_one_or_none=existing),
    )
    client = _make_client(mock_db)
    resp = client.post("/api/v1/agent/callback", json=CALLBACK_PAYLOAD)
    assert resp.status_code == 200
    mock_db.add.assert_not_called()
    assert existing.response_content == "the answer"


@pytest.mark.unit
def test_ai_callback_message_not_found_is_500_not_404():
    """PRE-EXISTING BUG: the 404 raised inside the try block is caught by
    the blanket `except Exception` and re-wrapped as a 500."""
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=None))
    client = _make_client(mock_db)
    resp = client.post("/api/v1/agent/callback", json=CALLBACK_PAYLOAD)
    assert resp.status_code == 500
    assert "Message not found" in resp.json()["detail"]


@pytest.mark.unit
def test_ai_callback_no_auth_required():
    """PRE-EXISTING BUG: no get_current_user_required call anywhere in this
    router; the callback endpoint accepts unauthenticated requests."""
    message = _mock_message()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_one_or_none=message),
        _exec_result(scalar_one_or_none=None),
    )
    client = _make_client(mock_db)
    resp = client.post("/api/v1/agent/callback", json=CALLBACK_PAYLOAD)
    assert resp.status_code == 200


@pytest.mark.unit
def test_ai_callback_validation_error_422():
    mock_db = _mock_db()
    client = _make_client(mock_db)
    resp = client.post("/api/v1/agent/callback", json={"message_id": "msg-1"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /status -> ai_status_update
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_ai_status_update_happy_path():
    existing = _mock_ai_response()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=existing))
    client = _make_client(mock_db)
    resp = client.post("/api/v1/agent/status", json={"message_id": "msg-1", "status": "processing"})
    assert resp.status_code == 200
    assert existing.status == "processing"
    mock_db.commit.assert_awaited_once()


@pytest.mark.unit
def test_ai_status_update_not_found_is_500_not_404():
    """PRE-EXISTING BUG: same blanket except-Exception re-wrap as above."""
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=None))
    client = _make_client(mock_db)
    resp = client.post("/api/v1/agent/status", json={"message_id": "msg-1", "status": "processing"})
    assert resp.status_code == 500
    assert "AI response not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /health -> ai_health_check
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_ai_health_check_happy_path():
    mock_db = _mock_db()
    client = _make_client(mock_db)
    resp = client.get("/api/v1/agent/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["provider"] == "openai"
    assert body["success_rate"] == 0.95


# ---------------------------------------------------------------------------
# GET /stats -> ai_stats
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_ai_stats_happy_path():
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_val=10),  # total
        _exec_result(scalar_val=7),  # successful
        _exec_result(scalar_val=2),  # failed
        _exec_result(scalar_val=150.5),  # avg time
        _exec_result(scalar_val=1500),  # total time
        _exec_result(scalar_val=3),  # today
        _exec_result(all_=[]),  # top providers
        _exec_result(all_=[]),  # top models
    )
    client = _make_client(mock_db)
    resp = client.get("/api/v1/agent/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_requests"] == 10
    assert body["successful_requests"] == 7
    assert body["failed_requests"] == 2
    assert body["requests_today"] == 3
    assert body["requests_this_week"] == 3  # "Simplified": same as today
    assert body["requests_this_month"] == 3  # "Simplified": same as today


@pytest.mark.unit
def test_ai_stats_null_avg_and_total_time_default_to_zero():
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_val=0),
        _exec_result(scalar_val=0),
        _exec_result(scalar_val=0),
        _exec_result(scalar_val=None),  # avg time None -> `or 0`
        _exec_result(scalar_val=None),  # total time None -> `or 0`
        _exec_result(scalar_val=0),
        _exec_result(all_=[]),
        _exec_result(all_=[]),
    )
    client = _make_client(mock_db)
    resp = client.get("/api/v1/agent/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["average_response_time_ms"] == 0.0
    assert body["total_processing_time_ms"] == 0


@pytest.mark.unit
def test_ai_stats_db_error_returns_500():
    mock_db = _mock_db()
    mock_db.execute = AsyncMock(side_effect=RuntimeError("db down"))
    client = _make_client(mock_db)
    resp = client.get("/api/v1/agent/stats")
    assert resp.status_code == 500
    assert "Failed to get AI stats" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /trigger/{message_id} -> trigger_ai_processing
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_trigger_ai_processing_happy_path_new_response():
    message = _mock_message()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_one_or_none=message),
        _exec_result(scalar_one_or_none=None),
    )
    with patch("app.routes.agent.trigger.process_ai_request", new=AsyncMock()):
        client = _make_client(mock_db)
        resp = client.post("/api/v1/agent/trigger/msg-1", json={"message_id": "msg-1"})
    assert resp.status_code == 200
    mock_db.add.assert_called_once()


@pytest.mark.unit
def test_trigger_ai_processing_existing_no_force_retry_is_500_not_400():
    """PRE-EXISTING BUG: the 400 "already triggered" HTTPException is raised
    inside the try block and re-wrapped as a 500 by the blanket except."""
    message = _mock_message()
    existing = _mock_ai_response()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_one_or_none=message),
        _exec_result(scalar_one_or_none=existing),
    )
    with patch("app.routes.agent.trigger.process_ai_request", new=AsyncMock()):
        client = _make_client(mock_db)
        resp = client.post("/api/v1/agent/trigger/msg-1", json={"message_id": "msg-1"})
    assert resp.status_code == 500
    assert "already triggered" in resp.json()["detail"]


@pytest.mark.unit
def test_trigger_ai_processing_force_retry_resets_existing_response():
    message = _mock_message()
    existing = _mock_ai_response(retry_count=1)
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_one_or_none=message),
        _exec_result(scalar_one_or_none=existing),
    )
    with patch("app.routes.agent.trigger.process_ai_request", new=AsyncMock()):
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/agent/trigger/msg-1",
            json={"message_id": "msg-1", "force_retry": True, "ai_provider": "anthropic"},
        )
    assert resp.status_code == 200
    assert existing.status == "pending"
    assert existing.retry_count == 2
    assert existing.ai_provider == "anthropic"


@pytest.mark.unit
def test_trigger_ai_processing_message_not_found_is_500_not_404():
    """PRE-EXISTING BUG: same blanket except-Exception re-wrap."""
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=None))
    client = _make_client(mock_db)
    resp = client.post("/api/v1/agent/trigger/msg-missing", json={"message_id": "msg-missing"})
    assert resp.status_code == 500
    assert "Message not found" in resp.json()["detail"]
