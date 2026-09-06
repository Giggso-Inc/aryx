"""
Golden-master / characterization tests for app/routes/support (package).

Purpose: support.py was 288 lines with 5 endpoints and had ZERO test
coverage before this file (confirmed via grep across tests/ for
"app.routes.support"). It has been split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5):
  app/routes/support/__init__.py     (router assembly)
  app/routes/support/helpers.py      (_support_detail_from_model,
                                       _generate_ticket_reference,
                                       _can_access_support_request,
                                       _can_access_company_support)
  app/routes/support/submit.py       (POST /submit)
  app/routes/support/company_list.py (GET /company/{company_id})
  app/routes/support/detail.py       (GET/PUT/DELETE /{request_id})

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included. Notable current behavior:
`POST /submit` never calls `get_current_user_required` — anyone (even
unauthenticated) can submit a support request, which is intentional per the
module docstring ("User-initiated support form"). The other four endpoints
(list-by-company, get, update, delete) all require auth.

Each submodule imports get_current_user_required into its own namespace, so
`_auth()` below takes the submodule name as a parameter. Similarly,
email_service is imported into submit.py's own namespace, so
`_patch_email()` targets "app.routes.support.submit.email_service" rather
than "app.routes.support.email_service".

Pattern follows tests/test_audit_characterization.py:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for the DB session; no real DB, no real HTTP.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.support import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/support")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    return db


def _auth(user, module):
    return patch(f"app.routes.support.{module}.get_current_user_required", new=AsyncMock(return_value=user))


def _exec_result(scalar_one_or_none=None, scalar_val=None, all_=None):
    m = MagicMock()
    m.scalar_one_or_none = MagicMock(return_value=scalar_one_or_none)
    m.scalar = MagicMock(return_value=scalar_val)
    scalars_mock = MagicMock()
    scalars_mock.all = MagicMock(return_value=all_ if all_ is not None else [])
    m.scalars = MagicMock(return_value=scalars_mock)
    return m


def _exec_seq(*results):
    return AsyncMock(side_effect=list(results))


def _uid():
    return uuid.uuid4()


def _mock_support_request(**overrides):
    sr = MagicMock()
    sr.id = _uid()
    sr.company_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    sr.company_name = "Acme Inc"
    sr.user_id = None
    sr.name = "Jane Doe"
    sr.email = "jane@example.com"
    sr.description = "Something is broken"
    sr.subject = "General"
    sr.ticket_reference = "SR-ABCD1234"
    sr.source = "Support form"
    sr.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for k, v in overrides.items():
        setattr(sr, k, v)
    return sr


SUBMIT_PAYLOAD = {
    "name": "Jane Doe",
    "email": "jane@example.com",
    "description": "Something is broken",
}


def _patch_email(sent_to_support=True):
    return patch.multiple(
        "app.routes.support.submit.email_service",
        send_support_request_email=MagicMock(return_value=sent_to_support),
        send_support_confirmation_email=MagicMock(return_value=True),
    )


# ---------------------------------------------------------------------------
# POST /submit -> submit_support_request
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_submit_support_request_happy_path_no_auth_required():
    mock_db = _mock_db()
    mock_db.refresh = AsyncMock(side_effect=lambda obj: None)
    with _patch_email(sent_to_support=True):
        client = _make_client(mock_db)
        resp = client.post("/api/v1/support/submit", json=SUBMIT_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["ticket_reference"].startswith("SR-")
    assert "submitted successfully" in body["message"]
    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.unit
def test_submit_support_request_support_email_failure_still_succeeds():
    """Current behavior: the API does NOT fail if notifying the support team
    fails; the request is still stored, and success=True is returned with a
    different message."""
    mock_db = _mock_db()
    mock_db.refresh = AsyncMock(side_effect=lambda obj: None)
    with _patch_email(sent_to_support=False):
        client = _make_client(mock_db)
        resp = client.post("/api/v1/support/submit", json=SUBMIT_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "could not send the notification" in body["message"]


@pytest.mark.unit
def test_submit_support_request_with_company_info():
    mock_db = _mock_db()
    mock_db.refresh = AsyncMock(side_effect=lambda obj: None)
    payload = dict(
        SUBMIT_PAYLOAD,
        subject="Billing",
        company_id=str(_uid()),
        company_name="  Acme Inc  ",
        user_id=str(_uid()),
    )
    with _patch_email(sent_to_support=True):
        client = _make_client(mock_db)
        resp = client.post("/api/v1/support/submit", json=payload)
    assert resp.status_code == 200


@pytest.mark.unit
def test_submit_support_request_validation_error_422():
    mock_db = _mock_db()
    client = _make_client(mock_db)
    resp = client.post("/api/v1/support/submit", json={"name": "Jane"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /company/{company_id} -> list_support_requests_by_company
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_list_by_company_happy_path(admin_user):
    admin_user.is_admin = True
    company_id = _uid()
    sr = _mock_support_request(company_id=company_id)
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_val=1),
        _exec_result(all_=[sr]),
    )
    with _auth(admin_user, "company_list"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/support/company/{company_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["pages"] == 1
    assert len(body["items"]) == 1


@pytest.mark.unit
def test_list_by_company_403_wrong_company(regular_user):
    regular_user.is_admin = False
    regular_user.company_id = "company-001"
    other_company = _uid()
    mock_db = _mock_db()
    with _auth(regular_user, "company_list"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/support/company/{other_company}")
    assert resp.status_code == 403


@pytest.mark.unit
def test_list_by_company_admin_can_access_any_company(admin_user):
    admin_user.is_admin = True
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_val=0),
        _exec_result(all_=[]),
    )
    with _auth(admin_user, "company_list"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/support/company/{_uid()}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["pages"] == 0


@pytest.mark.unit
def test_list_by_company_invalid_uuid_422():
    mock_db = _mock_db()
    client = _make_client(mock_db)
    resp = client.get("/api/v1/support/company/not-a-uuid")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /{request_id} -> get_support_request
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_support_request_happy_path(admin_user):
    admin_user.is_admin = True
    sr = _mock_support_request()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=sr))
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/support/{sr.id}")
    assert resp.status_code == 200
    assert resp.json()["ticket_reference"] == "SR-ABCD1234"


@pytest.mark.unit
def test_get_support_request_404_when_missing(admin_user):
    admin_user.is_admin = True
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=None))
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/support/{_uid()}")
    assert resp.status_code == 404


@pytest.mark.unit
def test_get_support_request_403_wrong_company(regular_user):
    regular_user.is_admin = False
    regular_user.company_id = "company-001"
    sr = _mock_support_request(company_id="company-999")
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=sr))
    with _auth(regular_user, "detail"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/support/{sr.id}")
    assert resp.status_code == 403


@pytest.mark.unit
def test_get_support_request_403_when_no_company_on_request(regular_user):
    """Current behavior: `_can_access_support_request` denies access (rather
    than allowing) when the support request has no company_id at all, even
    for a non-admin whose own company_id is set — there's no owner/user_id
    fallback check."""
    regular_user.is_admin = False
    sr = _mock_support_request(company_id=None)
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=sr))
    with _auth(regular_user, "detail"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/support/{sr.id}")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PUT /{request_id} -> update_support_request
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_update_support_request_happy_path(admin_user):
    admin_user.is_admin = True
    sr = _mock_support_request()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=sr))
    mock_db.refresh = AsyncMock(side_effect=lambda obj: None)
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.put(f"/api/v1/support/{sr.id}", json={"subject": "Updated"})
    assert resp.status_code == 200
    assert sr.subject == "Updated"
    mock_db.commit.assert_awaited_once()


@pytest.mark.unit
def test_update_support_request_404_when_missing(admin_user):
    admin_user.is_admin = True
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=None))
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.put(f"/api/v1/support/{_uid()}", json={"subject": "X"})
    assert resp.status_code == 404


@pytest.mark.unit
def test_update_support_request_403_wrong_company(regular_user):
    regular_user.is_admin = False
    regular_user.company_id = "company-001"
    sr = _mock_support_request(company_id="company-999")
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=sr))
    with _auth(regular_user, "detail"):
        client = _make_client(mock_db)
        resp = client.put(f"/api/v1/support/{sr.id}", json={"subject": "X"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /{request_id} -> delete_support_request
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_delete_support_request_happy_path(admin_user):
    admin_user.is_admin = True
    sr = _mock_support_request()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=sr))
    mock_db.delete = AsyncMock()
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.delete(f"/api/v1/support/{sr.id}")
    assert resp.status_code == 200
    assert "resolved" in resp.json()["message"]
    mock_db.delete.assert_awaited_once_with(sr)
    mock_db.commit.assert_awaited_once()


@pytest.mark.unit
def test_delete_support_request_404_when_missing(admin_user):
    admin_user.is_admin = True
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=None))
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.delete(f"/api/v1/support/{_uid()}")
    assert resp.status_code == 404


@pytest.mark.unit
def test_delete_support_request_403_wrong_company(regular_user):
    regular_user.is_admin = False
    regular_user.company_id = "company-001"
    sr = _mock_support_request(company_id="company-999")
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=sr))
    with _auth(regular_user, "detail"):
        client = _make_client(mock_db)
        resp = client.delete(f"/api/v1/support/{sr.id}")
    assert resp.status_code == 403
