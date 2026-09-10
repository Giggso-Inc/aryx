"""
Golden-master / characterization tests for app/routes/subscription_plans
(package).

Purpose: subscription_plans.py was 327 lines with 6 endpoints and had ZERO
test coverage before this file (confirmed via grep across tests/ for
"app.routes.subscription_plans"). It has been split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5):
  app/routes/subscription_plans/__init__.py   (router assembly)
  app/routes/subscription_plans/helpers.py    (validate_uuid)
  app/routes/subscription_plans/create.py     (POST /)
  app/routes/subscription_plans/list_plans.py (GET /)
  app/routes/subscription_plans/detail.py     (GET/PUT/DELETE /{plan_id})
  app/routes/subscription_plans/active.py     (GET /active/plans)

Each submodule imports get_current_user_required into its own namespace,
so `_auth()` below takes the submodule name as a parameter — patching the
single "app.routes.subscription_plans.active.get_current_user_required" from
before the split would not affect any submodule's own bound reference.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included. Notable current behavior
(not necessarily a bug, but worth documenting): `GET /active/plans` is
registered (in file/declaration order) AFTER `GET /{plan_id}`, but this does
not create a path-collision the way it would for e.g. `/company/my` vs
`/company/{company_id}` — `/active/plans` has two path segments after the
prefix while `/{plan_id}` has one, so FastAPI/Starlette never mis-routes
"/active/plans" to the `{plan_id}` handler. Registration order is preserved
exactly in the split regardless, per the wave B5 plan.

Pattern follows tests/test_audit_characterization.py /
tests/test_subscriptions_characterization.py:
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
    from app.routes.subscription_plans import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/subscription-plans")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    return db


def _auth(user, module):
    return patch(f"app.routes.subscription_plans.{module}.get_current_user_required", new=AsyncMock(return_value=user))


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


VALID_PLAN_PAYLOAD = {
    "name": "Pro",
    "plan_code": "pro-monthly",
    "monthly_price": "19.99",
    "plan_cycles": 12,
    "interval": 1,
    "interval_unit": "month",
    "interval_count": 1,
}


def _mock_plan(**overrides):
    p = MagicMock()
    p.id = _uid()
    p.name = "Pro"
    p.plan_code = "pro-monthly"
    p.description = None
    p.monthly_price = 19.99
    p.plan_cycles = 12
    p.interval = 1
    p.interval_unit = "month"
    p.interval_count = 1
    p.features = None
    p.sort_order = 0
    p.is_active = True
    p.zoho_plan_id = None
    p.zoho_product_id = None
    p.zoho_plan_code = None
    p.zoho_product_code = None
    p.zoho_billing_cycle = None
    p.platform_name = None
    p.created_by = None
    p.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    p.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    p.deleted_at = None
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


# ---------------------------------------------------------------------------
# POST / -> create_subscription_plan
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_create_plan_happy_path(admin_user):
    admin_user.is_admin = True
    admin_user.id = str(_uid())
    plan = _mock_plan()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=None))  # no existing plan_code
    mock_db.refresh = AsyncMock(side_effect=lambda obj: None)
    with _auth(admin_user, "create"):
        client = _make_client(mock_db)
        resp = client.post("/api/v1/subscription-plans/", json=VALID_PLAN_PAYLOAD)
    assert resp.status_code == 200
    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.unit
def test_create_plan_403_non_admin(regular_user):
    regular_user.is_admin = False
    mock_db = _mock_db()
    with _auth(regular_user, "create"):
        client = _make_client(mock_db)
        resp = client.post("/api/v1/subscription-plans/", json=VALID_PLAN_PAYLOAD)
    assert resp.status_code == 403


@pytest.mark.unit
def test_create_plan_409_duplicate_plan_code(admin_user):
    admin_user.is_admin = True
    existing = _mock_plan()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=existing))
    with _auth(admin_user, "create"):
        client = _make_client(mock_db)
        resp = client.post("/api/v1/subscription-plans/", json=VALID_PLAN_PAYLOAD)
    assert resp.status_code == 409


@pytest.mark.unit
def test_create_plan_invalid_interval_unit_422(admin_user):
    admin_user.is_admin = True
    mock_db = _mock_db()
    payload = dict(VALID_PLAN_PAYLOAD, interval_unit="fortnight")
    with _auth(admin_user, "create"):
        client = _make_client(mock_db)
        resp = client.post("/api/v1/subscription-plans/", json=payload)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET / -> list_subscription_plans
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_list_plans_happy_path_empty(admin_user):
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_val=0),  # count
        _exec_result(all_=[]),  # rows
    )
    with _auth(admin_user, "list_plans"):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/subscription-plans/")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"plans": [], "total": 0, "page": 1, "size": 10}


@pytest.mark.unit
def test_list_plans_with_filters_and_sort(admin_user):
    plan = _mock_plan()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_val=1),
        _exec_result(all_=[plan]),
    )
    with _auth(admin_user, "list_plans"):
        client = _make_client(mock_db)
        resp = client.get(
            "/api/v1/subscription-plans/",
            params={
                "search": "pro",
                "is_active": "true",
                "min_price": 5,
                "max_price": 50,
                "interval_unit": "MONTH",
                "sort_by": "monthly_price",
                "sort_order": "desc",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


# ---------------------------------------------------------------------------
# GET /{plan_id} -> get_subscription_plan
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_plan_happy_path(admin_user):
    plan = _mock_plan()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=plan))
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/subscription-plans/{plan.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(plan.id)


@pytest.mark.unit
def test_get_plan_invalid_uuid_400(admin_user):
    mock_db = _mock_db()
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/subscription-plans/not-a-uuid")
    assert resp.status_code == 400
    assert "plan ID" in resp.json()["detail"]


@pytest.mark.unit
def test_get_plan_404_when_missing(admin_user):
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=None))
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.get(f"/api/v1/subscription-plans/{_uid()}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /{plan_id} -> update_subscription_plan
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_update_plan_happy_path(admin_user):
    admin_user.is_admin = True
    admin_user.id = str(_uid())
    plan = _mock_plan()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=plan))
    mock_db.refresh = AsyncMock(side_effect=lambda obj: None)
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.put(f"/api/v1/subscription-plans/{plan.id}", json={"name": "Pro Plus"})
    assert resp.status_code == 200
    assert plan.name == "Pro Plus"
    assert plan.updated_by == admin_user.id


@pytest.mark.unit
def test_update_plan_403_non_admin(regular_user):
    regular_user.is_admin = False
    mock_db = _mock_db()
    with _auth(regular_user, "detail"):
        client = _make_client(mock_db)
        resp = client.put(f"/api/v1/subscription-plans/{_uid()}", json={"name": "X"})
    assert resp.status_code == 403


@pytest.mark.unit
def test_update_plan_invalid_uuid_400(admin_user):
    admin_user.is_admin = True
    mock_db = _mock_db()
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.put("/api/v1/subscription-plans/not-a-uuid", json={"name": "X"})
    assert resp.status_code == 400


@pytest.mark.unit
def test_update_plan_404_when_missing(admin_user):
    admin_user.is_admin = True
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=None))
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.put(f"/api/v1/subscription-plans/{_uid()}", json={"name": "X"})
    assert resp.status_code == 404


@pytest.mark.unit
def test_update_plan_409_when_new_code_conflicts(admin_user):
    admin_user.is_admin = True
    plan = _mock_plan(plan_code="old-code")
    conflicting = _mock_plan(plan_code="new-code")
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(
        _exec_result(scalar_one_or_none=plan),
        _exec_result(scalar_one_or_none=conflicting),
    )
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.put(f"/api/v1/subscription-plans/{plan.id}", json={"plan_code": "new-code"})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# DELETE /{plan_id} -> delete_subscription_plan
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_delete_plan_happy_path_soft_deletes(admin_user):
    admin_user.is_admin = True
    plan = _mock_plan()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=plan))
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.delete(f"/api/v1/subscription-plans/{plan.id}")
    assert resp.status_code == 200
    assert plan.is_active is False
    assert plan.deleted_at is not None
    mock_db.commit.assert_awaited_once()


@pytest.mark.unit
def test_delete_plan_403_non_admin(regular_user):
    regular_user.is_admin = False
    mock_db = _mock_db()
    with _auth(regular_user, "detail"):
        client = _make_client(mock_db)
        resp = client.delete(f"/api/v1/subscription-plans/{_uid()}")
    assert resp.status_code == 403


@pytest.mark.unit
def test_delete_plan_invalid_uuid_400(admin_user):
    admin_user.is_admin = True
    mock_db = _mock_db()
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.delete("/api/v1/subscription-plans/not-a-uuid")
    assert resp.status_code == 400


@pytest.mark.unit
def test_delete_plan_404_when_missing(admin_user):
    admin_user.is_admin = True
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(scalar_one_or_none=None))
    with _auth(admin_user, "detail"):
        client = _make_client(mock_db)
        resp = client.delete(f"/api/v1/subscription-plans/{_uid()}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /active/plans -> get_active_plans
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_active_plans_happy_path(admin_user):
    plan = _mock_plan()
    mock_db = _mock_db()
    mock_db.execute = _exec_seq(_exec_result(all_=[plan]))
    with _auth(admin_user, "active"):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/subscription-plans/active/plans")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == str(plan.id)


@pytest.mark.unit
def test_get_active_plans_401_unauthenticated():
    from fastapi import HTTPException, status as http_status

    mock_db = _mock_db()
    with patch(
        "app.routes.subscription_plans.active.get_current_user_required",
        new=AsyncMock(side_effect=HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Authentication required")),
    ):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/subscription-plans/active/plans")
    assert resp.status_code == 401



