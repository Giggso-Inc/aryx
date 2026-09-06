"""
Golden-master / characterization tests for app/routes/subscriptions.py.

Purpose: subscriptions.py is 529 lines with 7 endpoints and had ZERO test
coverage before this file. It is about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2). Before the
split, we capture the CURRENT observable behavior of every endpoint so the
split can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included.

Pattern follows tests/test_channels_characterization.py:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.
- `asyncio.run()` is not needed here — TestClient handles the event loop.

Do not modify app/routes/subscriptions.py (or the split package) from this
file's tests beyond what the split itself requires (patch targets).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.subscriptions import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/subscriptions")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _auth(user, module):
    """Patch get_current_user_required on the specific submodule that owns
    the endpoint under test. Each submodule in app/routes/subscriptions/
    imports get_current_user_required itself, so patching the package
    (app.routes.subscriptions.create.get_current_user_required) would NOT affect
    the submodule's own bound reference — this is the split's "CRITICAL
    GOTCHA" from the compliance plan: patch the exact module path, not the
    re-exporting package.
    """
    return patch(f"app.routes.subscriptions.{module}.get_current_user_required", new=AsyncMock(return_value=user))


class _FakeResult:
    """Mimics the subset of SQLAlchemy's async Result API these endpoints
    call: .scalar_one_or_none(), .scalars().all(), .scalar(), .first()."""

    def __init__(self, scalar_one_or_none=None, all_=None, scalar_val=None, first_=None):
        self._son = scalar_one_or_none
        self._all = all_ if all_ is not None else []
        self._scalar_val = scalar_val
        self._first = first_

    def scalar_one_or_none(self):
        return self._son

    def scalars(self):
        m = MagicMock()
        m.all = MagicMock(return_value=self._all)
        return m

    def scalar(self):
        return self._scalar_val

    def first(self):
        return self._first


def _exec_seq(*results):
    return AsyncMock(side_effect=list(results))


def _uid():
    return uuid.uuid4()


def _mock_company(**overrides):
    c = MagicMock()
    c.id = _uid()
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


def _mock_plan(**overrides):
    p = MagicMock()
    p.id = _uid()
    p.name = "Pro Plan"
    p.plan_code = "pro"
    p.features = {"max_users": 50}
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def _mock_subscription(**overrides):
    now = datetime.now(timezone.utc)
    s = MagicMock()
    s.id = _uid()
    s.company_id = _uid()
    s.plan_id = _uid()
    s.status = "active"
    s.subscription_status = "active"
    s.amount = Decimal("99.00")
    s.currency_code = "USD"
    s.billing_cycle = "monthly"
    s.auto_collect = True
    s.current_period_start = now
    s.current_period_end = now + timedelta(days=30)
    s.next_billing_date = now + timedelta(days=30)
    s.zoho_trial_end = None
    s.zoho_cancel_at_period_end = False
    s.usage_limits = None
    s.zoho_subscription_id = None
    s.zoho_customer_id = None
    s.zoho_hosted_page_id = None
    s.zoho_invoice_id = None
    s.zoho_payment_id = None
    s.platform_name = None
    s.created_at = now
    s.updated_at = now
    s.deleted_at = None
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


@pytest.fixture
def admin_user(admin_user):
    admin_user.is_admin = True
    return admin_user


@pytest.fixture
def regular_user(regular_user):
    regular_user.is_admin = False
    return regular_user


# ===========================================================================
# POST / — create_subscription
# ===========================================================================

class TestCreateSubscription:
    def _payload(self, company_id, plan_id, **overrides):
        now = datetime.now(timezone.utc)
        payload = {
            "company_id": str(company_id),
            "plan_id": str(plan_id),
            "status": "active",
            "subscription_status": "active",
            "amount": "99.00",
            "currency_code": "USD",
            "billing_cycle": "monthly",
            "current_period_start": now.isoformat(),
            "current_period_end": (now + timedelta(days=30)).isoformat(),
        }
        payload.update(overrides)
        return payload

    def test_non_admin_403(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "create"):
            resp = client.post(
                "/api/v1/subscriptions/",
                json=self._payload(_uid(), _uid()),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Only admins can create subscriptions"

    def test_company_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post(
                "/api/v1/subscriptions/",
                json=self._payload(_uid(), _uid()),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Company not found"

    def test_success_creates_subscription(self, mock_db, admin_user):
        company = _mock_company()
        plan = _mock_plan()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=company),  # company lookup
            _FakeResult(scalar_one_or_none=plan),      # plan lookup
            _FakeResult(scalar_one_or_none=None),       # no existing subscription
        )

        async def _refresh(obj):
            return None

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db)
        with _auth(admin_user, "create"):
            resp = client.post(
                "/api/v1/subscriptions/",
                json=self._payload(company.id, plan.id),
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"


# ===========================================================================
# GET / — list_subscriptions
# ===========================================================================

class TestListSubscriptions:
    def test_non_admin_returns_500_due_to_status_param_shadowing(self, mock_db, regular_user):
        """PRE-EXISTING BUG (characterized, not fixed): list_subscriptions
        declares a query parameter named `status: Optional[str] = None`,
        which shadows the module-level `from fastapi import status` import
        inside this function's scope. When a non-admin hits this endpoint,
        the intended `raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, ...)`
        tries to read `.HTTP_403_FORBIDDEN` off the local `status` parameter
        (None by default) instead of the fastapi module, raising
        AttributeError → 500, never the intended 403."""
        client = _make_client(mock_db)
        with _auth(regular_user, "list_subscriptions"):
            resp = client.get("/api/v1/subscriptions/", headers=AUTH_HEADERS)
        assert resp.status_code == 500

    def test_admin_success_empty(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_val=0),  # count
            _FakeResult(all_=[]),        # subscriptions
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "list_subscriptions"):
            resp = client.get("/api/v1/subscriptions/", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["subscriptions"] == []
        assert body["total"] == 0

    def test_admin_success_with_results(self, mock_db, admin_user):
        sub = _mock_subscription()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_val=1),
            _FakeResult(all_=[sub]),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "list_subscriptions"):
            resp = client.get("/api/v1/subscriptions/", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()["subscriptions"]) == 1


# ===========================================================================
# GET /{subscription_id} — get_subscription
# ===========================================================================

class TestGetSubscription:
    def test_invalid_uuid_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.get("/api/v1/subscriptions/not-a-uuid", headers=AUTH_HEADERS)
        assert resp.status_code == 400

    def test_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.get(f"/api/v1/subscriptions/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_access_denied_for_other_company_403(self, mock_db, regular_user):
        sub = _mock_subscription(company_id=_uid())
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=sub))
        client = _make_client(mock_db)
        with _auth(regular_user, "detail"):
            resp = client.get(f"/api/v1/subscriptions/{sub.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 403

    def test_success(self, mock_db, admin_user):
        sub = _mock_subscription()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=sub))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.get(f"/api/v1/subscriptions/{sub.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["id"] == str(sub.id)


# ===========================================================================
# PUT /{subscription_id} — update_subscription
# ===========================================================================

class TestUpdateSubscription:
    def test_non_admin_403(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "detail"):
            resp = client.put(
                f"/api/v1/subscriptions/{_uid()}",
                json={"status": "cancelled"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 403

    def test_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.put(
                f"/api/v1/subscriptions/{_uid()}",
                json={"status": "cancelled"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 404

    def test_success(self, mock_db, admin_user):
        sub = _mock_subscription()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=sub))

        async def _refresh(obj):
            return None

        mock_db.refresh = AsyncMock(side_effect=_refresh)
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.put(
                f"/api/v1/subscriptions/{sub.id}",
                json={"status": "cancelled"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"


# ===========================================================================
# DELETE /{subscription_id} — delete_subscription
# ===========================================================================

class TestDeleteSubscription:
    def test_non_admin_403(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "detail"):
            resp = client.delete(f"/api/v1/subscriptions/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 403

    def test_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.delete(f"/api/v1/subscriptions/{_uid()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_success_soft_delete(self, mock_db, admin_user):
        sub = _mock_subscription()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=sub))
        client = _make_client(mock_db)
        with _auth(admin_user, "detail"):
            resp = client.delete(f"/api/v1/subscriptions/{sub.id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["message"] == "Subscription deleted successfully"
        assert sub.status == "inactive"
        assert sub.subscription_status == "inactive"
        assert sub.deleted_at is not None


# ===========================================================================
# GET /company/my/current-plan — get_my_company_current_plan
# ===========================================================================

class TestGetMyCompanyCurrentPlan:
    def test_user_without_company_returns_free_plan(self, mock_db, admin_user):
        admin_user.company_id = None
        client = _make_client(mock_db)
        with _auth(admin_user, "company_plan_mine"):
            resp = client.get("/api/v1/subscriptions/company/my/current-plan", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["plan_code"] == "free"
        assert body["is_trial"] is False

    def test_no_active_subscription_returns_free_plan(self, mock_db, admin_user):
        admin_user.company_id = _uid()
        mock_db.execute = _exec_seq(_FakeResult(first_=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "company_plan_mine"):
            resp = client.get("/api/v1/subscriptions/company/my/current-plan", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["plan_code"] == "free"

    def test_active_subscription_returns_real_plan(self, mock_db, admin_user):
        admin_user.company_id = _uid()
        sub = _mock_subscription(company_id=admin_user.company_id, next_billing_date=None)
        plan = _mock_plan()
        mock_db.execute = _exec_seq(_FakeResult(first_=(sub, plan)))
        client = _make_client(mock_db)
        with _auth(admin_user, "company_plan_mine"):
            resp = client.get("/api/v1/subscriptions/company/my/current-plan", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["plan_code"] == plan.plan_code
        assert body["plan_name"] == plan.name


# ===========================================================================
# GET /company/{company_id}/current-plan — get_company_current_plan
# ===========================================================================

class TestGetCompanyCurrentPlan:
    def test_invalid_uuid_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "company_plan_by_id"):
            resp = client.get("/api/v1/subscriptions/company/not-a-uuid/current-plan", headers=AUTH_HEADERS)
        assert resp.status_code == 400

    def test_company_not_found_404(self, mock_db, admin_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(admin_user, "company_plan_by_id"):
            resp = client.get(f"/api/v1/subscriptions/company/{_uid()}/current-plan", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_access_denied_for_other_company_403(self, mock_db, regular_user):
        company = _mock_company()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=company))
        client = _make_client(mock_db)
        with _auth(regular_user, "company_plan_by_id"):
            resp = client.get(f"/api/v1/subscriptions/company/{company.id}/current-plan", headers=AUTH_HEADERS)
        assert resp.status_code == 403

    def test_success_no_subscription_returns_free_plan(self, mock_db, admin_user):
        company = _mock_company()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=company),
            _FakeResult(first_=None),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "company_plan_by_id"):
            resp = client.get(f"/api/v1/subscriptions/company/{company.id}/current-plan", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["plan_code"] == "free"

    def test_success_with_subscription(self, mock_db, admin_user):
        company = _mock_company()
        sub = _mock_subscription(company_id=company.id)
        plan = _mock_plan()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=company),
            _FakeResult(first_=(sub, plan)),
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "company_plan_by_id"):
            resp = client.get(f"/api/v1/subscriptions/company/{company.id}/current-plan", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["plan_code"] == plan.plan_code
