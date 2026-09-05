"""
Golden-master / characterization tests for the app/routes/payment_gateway
package (split from the original monolithic app/routes/payment_gateway.py,
2,505 lines, 13 endpoints, ZERO original test coverage).

Purpose: capture the CURRENT observable behavior of every one of the 13
endpoints so the file split (and any future refactor) can be verified to
change nothing. These are characterization tests, not "correctness" tests:
assertions match what the code actually does today, bugs included.

Pattern follows tests/test_channels_characterization.py exactly:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.
- `asyncio.run()` is not needed here (TestClient handles the event loop);
  no pytest-asyncio plugin is installed, so every test stays synchronous.

CRITICAL GOTCHA (patch targets): each submodule under app/routes/
payment_gateway/ imports get_current_user_required and get_zoho_service
itself (`from app.middleware.auth_middleware import get_current_user_required`,
`from app.services.zoho_service import get_zoho_service`). Patching the
package path (app.routes.payment_gateway.get_zoho_service) would NOT affect
a submodule's own bound reference. Every patch() below targets the exact
submodule that owns the endpoint under test, e.g.
`app.routes.payment_gateway.hosted_pages.get_zoho_service`.

Documented pre-existing bugs (found while reading the ground-truth code,
characterized as-is, NOT fixed):

1. webhook.zoho_subscription_webhook: the docstring/comment says "Verify
   webhook signature (implement proper verification)" but no signature
   check is ever performed — any payload is accepted and always returns
   success=True. See TestWebhook.test_no_signature_verification_is_a_noop.

2. invoice_download.download_invoice: when the requested invoice_id is NOT
   found among the customer's Zoho invoices, the code raises
   HTTPException(403, "Invoice does not belong to your company") from
   *inside* an `except Exception as verify_error` block's try — but that
   raise is itself inside a `try/except Exception as verify_error` that
   catches it, logs a warning, and swallows it (HTTPException is an
   Exception subclass). Execution then falls through and downloads the PDF
   anyway. See TestDownloadInvoice.test_ownership_check_403_is_swallowed_bug.

3. helpers.parse_features_to_limits / extract_price_from_brackets: dead
   code, not called by any of the 13 endpoints or by any other module
   (confirmed by grep) — carried over verbatim, not exercised here since
   they are not reachable from any route.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def _make_client(mock_db, with_user_state=None):
    """Build a TestClient wired to the payment_gateway package router.

    If `with_user_state` is given, a tiny middleware sets
    `request.state.user_id` before the request reaches the endpoint — this
    stands in for the real AuthMiddleware (not mounted in these tests) and
    is required by download_invoice, which reads request.state.user_id
    directly instead of via a dependency.
    """
    from app.core.database import get_db
    from app.routes.payment_gateway import router

    app = FastAPI()

    if with_user_state is not None:
        @app.middleware("http")
        async def _inject_user_id(request, call_next):
            request.state.user_id = with_user_state
            return await call_next(request)

    app.include_router(router, prefix="/api/v1/payment-gateway")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


def _auth(user, module):
    """Patch get_current_user_required on the exact submodule that owns the
    endpoint under test (see module docstring's CRITICAL GOTCHA note)."""
    return patch(f"app.routes.payment_gateway.{module}.get_current_user_required", new=AsyncMock(return_value=user))


def _zoho(module, instance):
    """Patch get_zoho_service on the exact submodule that owns the endpoint
    under test, returning `instance` regardless of platform_name arg."""
    return patch(f"app.routes.payment_gateway.{module}.get_zoho_service", new=MagicMock(return_value=instance))


class _FakeResult:
    """Mimics the subset of SQLAlchemy's async Result API these endpoints
    call: .scalar_one_or_none(), .scalars().all(), .scalar()."""

    def __init__(self, scalar_one_or_none=None, all_=None, scalar_val=None):
        self._son = scalar_one_or_none
        self._all = all_ if all_ is not None else []
        self._scalar_val = scalar_val

    def scalar_one_or_none(self):
        return self._son

    def scalars(self):
        m = MagicMock()
        m.all = MagicMock(return_value=self._all)
        return m

    def scalar(self):
        return self._scalar_val


def _exec_seq(*results):
    return AsyncMock(side_effect=list(results))


def _uid():
    return uuid.uuid4()


def _mock_plan(**overrides):
    p = MagicMock()
    p.id = _uid()
    p.name = "Pro"
    p.plan_code = "pro-monthly"
    p.description = "Pro plan"
    p.monthly_price = Decimal("49.00")
    p.interval = 1
    p.interval_unit = "months"
    p.zoho_billing_cycle = "1 months"
    p.features = ["10 Channels", "1000 Messages", "5GB Storage"]
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def _mock_company(**overrides):
    c = MagicMock()
    c.id = _uid()
    c.name = "Acme Inc"
    c.subscription_plan = None
    c.is_active = False
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


def _mock_subscription(**overrides):
    s = MagicMock()
    s.id = _uid()
    s.company_id = _uid()
    s.plan_id = _uid()
    s.status = "active"
    s.zoho_subscription_id = "zsub-001"
    s.zoho_customer_id = "zcust-001"
    s.amount = Decimal("49.00")
    s.next_billing_date = None
    s.current_period_end = None
    s.usage_limits = None
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@pytest.fixture
def admin_user(admin_user):
    admin_user.role = "admin"
    return admin_user


@pytest.fixture
def regular_user(regular_user):
    regular_user.role = "user"
    return regular_user


# ===========================================================================
# POST /zoho/subscriptions/hostedPage/create — create_zoho_hosted_page
# ===========================================================================

class TestCreateHostedPage:
    def _payload(self, **overrides):
        payload = {
            "plan": {"name": "Pro", "planCode": "pro-monthly"},
            "redirectUrl": "https://example.com/redirect",
            "customer": {"companyName": "Acme Inc", "email": "a@acme.com", "displayName": "Acme"},
        }
        payload.update(overrides)
        return payload

    def test_plan_not_found_404(self, mock_db):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        resp = client.post("/api/v1/payment-gateway/zoho/subscriptions/hostedPage/create", json=self._payload())
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Plan not found"

    def test_happy_path_uses_real_zoho_response(self, mock_db):
        plan = _mock_plan()
        company = _mock_company()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=plan),
            _FakeResult(scalar_one_or_none=company),
            _FakeResult(scalar_one_or_none=None),  # no existing subscription
        )
        zoho_instance = MagicMock()
        zoho_instance.create_hosted_page = AsyncMock(
            return_value={"hostedPageId": "hp-123", "hostedPageUrl": "https://zoho.example/hp-123"}
        )
        client = _make_client(mock_db)
        with _zoho("hosted_pages", zoho_instance):
            resp = client.post("/api/v1/payment-gateway/zoho/subscriptions/hostedPage/create", json=self._payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["hostedPageId"] == "hp-123"
        assert body["data"]["url"] == "https://zoho.example/hp-123"
        assert body["message"] == "Zoho hosted payment page created successfully"

    def test_zoho_failure_falls_back_to_mock_response(self, mock_db):
        """Characterizes the fallback branch: any exception from the Zoho
        call (including a malformed/missing hostedPageUrl) produces a 200
        with a locally-generated hosted page URL rather than an error."""
        plan = _mock_plan()
        company = _mock_company()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=plan),
            _FakeResult(scalar_one_or_none=company),
            _FakeResult(scalar_one_or_none=None),
        )
        zoho_instance = MagicMock()
        zoho_instance.create_hosted_page = AsyncMock(side_effect=RuntimeError("zoho down"))
        client = _make_client(mock_db)
        with _zoho("hosted_pages", zoho_instance):
            resp = client.post("/api/v1/payment-gateway/zoho/subscriptions/hostedPage/create", json=self._payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "Hosted payment page created (fallback mode)"
        assert "hosted-page/" in body["data"]["url"]


# ===========================================================================
# GET /zoho/subscriptions/fetchByHostedId/{hostedPageId} — fetch_by_hosted_id
# ===========================================================================

class TestFetchByHostedId:
    def test_non_admin_403(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "hosted_pages_fetch"):
            resp = client.get("/api/v1/payment-gateway/zoho/subscriptions/fetchByHostedId/hp-123", headers=AUTH_HEADERS)
        assert resp.status_code == 403

    def test_admin_happy_path(self, mock_db, admin_user):
        zoho_instance = MagicMock()
        zoho_instance.base_url = "https://prism.zoho.example/billing/v1"
        client = _make_client(mock_db)
        with _auth(admin_user, "hosted_pages_fetch"), _zoho("hosted_pages_fetch", zoho_instance):
            resp = client.get("/api/v1/payment-gateway/zoho/subscriptions/fetchByHostedId/hp-123", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["hostedPageId"] == "hp-123"
        assert body["data"]["url"] == "https://prism.zoho.example/hosted-page/hp-123"


# ===========================================================================
# PUT /zoho/subscriptions/hostedPage/update — update_subscription_hosted_page
# ===========================================================================

class TestUpdateSubscriptionHostedPage:
    def test_non_admin_403(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "hosted_pages_update"):
            resp = client.put(
                "/api/v1/payment-gateway/zoho/subscriptions/hostedPage/update",
                json={"subscriptionId": "zsub-001"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 403

    def test_admin_happy_path(self, mock_db, admin_user):
        zoho_instance = MagicMock()
        zoho_instance.update_subscription_hosted_page = AsyncMock(return_value={"hostedPageId": "hp-999"})
        client = _make_client(mock_db)
        with _auth(admin_user, "hosted_pages_update"), _zoho("hosted_pages_update", zoho_instance):
            resp = client.put(
                "/api/v1/payment-gateway/zoho/subscriptions/hostedPage/update",
                json={"subscriptionId": "zsub-001"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["hostedPageId"] == "hp-999"


# ===========================================================================
# POST /zoho/subscriptions/create — create_zoho_subscription
# ===========================================================================

class TestCreateZohoSubscription:
    def _payload(self, **overrides):
        payload = {"plan": {"planCode": "pro-monthly", "quantity": 1}}
        payload.update(overrides)
        return payload

    def test_company_not_found_404(self, mock_db, regular_user):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        with _auth(regular_user, "subscription_create"):
            resp = client.post("/api/v1/payment-gateway/zoho/subscriptions/create", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_happy_path_creates_new_local_subscription(self, mock_db, regular_user):
        company = _mock_company()
        plan = _mock_plan()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=company),
            _FakeResult(scalar_one_or_none=plan),  # plan lookup by plan_code
            _FakeResult(scalar_one_or_none=None),  # no existing local subscription
            _FakeResult(),  # update(Company).values(subscription_plan=...)
        )
        zoho_instance = MagicMock()
        zoho_instance.create_subscription = AsyncMock(return_value={
            "subscription": {
                "subscription_id": "zsub-new-001",
                "customer_id": "zcust-new-001",
                "plan": {"plan_code": "pro-monthly", "name": "Pro"},
                "amount": 49.0,
                "currency_code": "USD",
                "interval": 1,
                "interval_unit": "months",
                "status": "live",
            }
        })
        client = _make_client(mock_db)
        with _auth(regular_user, "subscription_create"), _zoho("subscription_create", zoho_instance):
            resp = client.post("/api/v1/payment-gateway/zoho/subscriptions/create", json=self._payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        mock_db.commit.assert_awaited()

    def test_plan_code_not_found_locally_returns_success_false_400(self, mock_db, regular_user):
        company = _mock_company()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=company),
            _FakeResult(scalar_one_or_none=None),  # plan lookup fails
        )
        zoho_instance = MagicMock()
        zoho_instance.create_subscription = AsyncMock(return_value={
            "subscription": {"subscription_id": "zsub-002", "plan": {"plan_code": "missing-plan"}}
        })
        client = _make_client(mock_db)
        with _auth(regular_user, "subscription_create"), _zoho("subscription_create", zoho_instance):
            resp = client.post("/api/v1/payment-gateway/zoho/subscriptions/create", json=self._payload(), headers=AUTH_HEADERS)
        # Note: this branch returns a SuccessResponse with success=False and an
        # embedded code=400, but the actual HTTP status is still 200 (no
        # explicit status_code was set on the route) — characterizing as-is.
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["code"] == 400


# ===========================================================================
# POST /zoho/subscriptions/updateCompanyPlan — update_company_plan
# ===========================================================================

class TestUpdateCompanyPlan:
    def test_non_admin_403(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "subscription_plan_update"):
            resp = client.post(
                "/api/v1/payment-gateway/zoho/subscriptions/updateCompanyPlan",
                json={"companyId": str(_uid()), "newPlanId": str(_uid())},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 403

    def test_missing_required_fields_400(self, mock_db, admin_user):
        client = _make_client(mock_db)
        with _auth(admin_user, "subscription_plan_update"):
            resp = client.post(
                "/api/v1/payment-gateway/zoho/subscriptions/updateCompanyPlan",
                json={"companyId": str(_uid())},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400

    def test_happy_path(self, mock_db, admin_user):
        company_id = str(_uid())
        plan = _mock_plan()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=_mock_company(id=company_id)),
            _FakeResult(scalar_one_or_none=plan),
            _FakeResult(),  # mark previous subscriptions inactive (update, no scalar needed)
            _FakeResult(),  # update company plan
        )
        client = _make_client(mock_db)
        with _auth(admin_user, "subscription_plan_update"):
            resp = client.post(
                "/api/v1/payment-gateway/zoho/subscriptions/updateCompanyPlan",
                json={"companyId": company_id, "newPlanId": str(plan.id)},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        mock_db.commit.assert_awaited()


# ===========================================================================
# POST /zoho/subscriptions/cancel — cancel_subscription_new
# ===========================================================================

class TestCancelSubscription:
    def test_happy_path(self, mock_db, regular_user):
        subscription = _mock_subscription()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=subscription),
            _FakeResult(),  # update(Subscription).values(status="inactive", ...)
        )
        zoho_instance = MagicMock()
        zoho_instance.cancel_subscription = AsyncMock(return_value={"subscription": {"current_term_ends_at": "2026-12-01"}})
        client = _make_client(mock_db)
        with _auth(regular_user, "subscription_cancel"), _zoho("subscription_cancel", zoho_instance):
            resp = client.post(
                "/api/v1/payment-gateway/zoho/subscriptions/cancel",
                json={"subscriptionId": "zsub-001", "cancelAtEnd": True},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        mock_db.commit.assert_awaited()

    def test_zoho_returns_none_success_false(self, mock_db, regular_user):
        zoho_instance = MagicMock()
        zoho_instance.cancel_subscription = AsyncMock(return_value=None)
        client = _make_client(mock_db)
        with _auth(regular_user, "subscription_cancel"), _zoho("subscription_cancel", zoho_instance):
            resp = client.post(
                "/api/v1/payment-gateway/zoho/subscriptions/cancel",
                json={"subscriptionId": "zsub-001", "cancelAtEnd": True},
                headers=AUTH_HEADERS,
            )
        # As with create_zoho_subscription, HTTP status stays 200 even though
        # the embedded body reports success=False / code=500.
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["code"] == 500


# ===========================================================================
# POST /zoho/subscriptions/reactivate — reactivate_zoho_subscription
# ===========================================================================

class TestReactivateSubscription:
    def test_happy_path(self, mock_db, regular_user):
        subscription = _mock_subscription()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=subscription),
            _FakeResult(),  # update(Subscription).values(status="active", ...)
        )
        zoho_instance = MagicMock()
        zoho_instance.reactivate_subscription = AsyncMock(return_value={"subscription": {"status": "live"}})
        client = _make_client(mock_db)
        with _auth(regular_user, "subscription_reactivate"), _zoho("subscription_reactivate", zoho_instance):
            resp = client.post(
                "/api/v1/payment-gateway/zoho/subscriptions/reactivate",
                json={"subscriptionId": "zsub-001"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_zoho_invalid_subscription_id_maps_to_400(self, mock_db, regular_user):
        zoho_instance = MagicMock()
        zoho_instance.reactivate_subscription = AsyncMock(
            side_effect=RuntimeError("Zoho API error: 400 - invalid subscription id 107202")
        )
        client = _make_client(mock_db)
        with _auth(regular_user, "subscription_reactivate"), _zoho("subscription_reactivate", zoho_instance):
            resp = client.post(
                "/api/v1/payment-gateway/zoho/subscriptions/reactivate",
                json={"subscriptionId": "bad-id"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400


# ===========================================================================
# POST /zoho/subscriptions/validatePayment — validate_payment
# ===========================================================================

class TestValidatePayment:
    def test_neither_hostedpageid_nor_subscriptionid_success_false_400(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "validate_payment"):
            resp = client.post(
                "/api/v1/payment-gateway/zoho/subscriptions/validatePayment",
                json={"companyId": str(_uid())},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["code"] == 400

    def test_happy_path_via_hosted_page(self, mock_db, regular_user):
        company_id = str(_uid())
        company = _mock_company(id=company_id)
        plan = _mock_plan(plan_code="pro-monthly")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=company),  # company lookup
            _FakeResult(scalar_one_or_none=None),  # existing subscription lookup -> none, so plan_code path used
            _FakeResult(scalar_one_or_none=plan),  # plan lookup by plan_code (new-subscription branch)
            _FakeResult(),  # update(Company).values(subscription_plan=..., is_active=True)
            _FakeResult(),  # update(Subscription) mark other subscriptions inactive
        )
        zoho_instance = MagicMock()
        zoho_instance.get_hosted_page = AsyncMock(return_value={
            "data": {
                "subscription": {
                    "subscription_id": "zsub-live-001",
                    "status": "live",
                    "customer": {"customer_id": "zcust-001"},
                    "plan": {"plan_code": "pro-monthly", "name": "Pro"},
                    "amount": 49.0,
                },
                "invoice": {"payment_made": 49.0, "balance": 0},
            }
        })
        client = _make_client(mock_db)
        with _auth(regular_user, "validate_payment"), _zoho("validate_payment", zoho_instance):
            resp = client.post(
                "/api/v1/payment-gateway/zoho/subscriptions/validatePayment",
                json={"companyId": company_id, "hostedPageId": "hp-123"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "active"
        mock_db.commit.assert_awaited()


# ===========================================================================
# POST /zoho/webhook/subscription — zoho_subscription_webhook
# ===========================================================================

class TestWebhook:
    def test_happy_path(self, mock_db):
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/payment-gateway/zoho/webhook/subscription",
            json={"event_type": "subscription_activation", "data": {"subscription_id": "zsub-001"}},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["webhook_processed"] is True

    def test_no_signature_verification_is_a_noop(self, mock_db):
        """Documented pre-existing bug (see module docstring #1): the
        endpoint never validates any signature/secret on the payload — an
        arbitrary/forged body is accepted exactly like a genuine one."""
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/payment-gateway/zoho/webhook/subscription",
            json={"totally": "unsigned", "forged": True},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ===========================================================================
# POST /zoho/subscriptions/validation/{user_id} — subscription_validation
# ===========================================================================

class TestSubscriptionValidation:
    def test_invalid_user_id_400(self, mock_db):
        client = _make_client(mock_db)
        resp = client.post("/api/v1/payment-gateway/zoho/subscriptions/validation/not-a-uuid")
        assert resp.status_code == 400

    def test_channel_only_check_happy_path(self, mock_db):
        user_id = str(_uid())
        user = MagicMock()
        user.id = user_id
        user.company_id = str(_uid())
        subscription = _mock_subscription()
        plan = _mock_plan()
        with patch("app.core.config.settings.IS_MARKETPLACE", False):
            mock_db.execute = _exec_seq(
                _FakeResult(scalar_one_or_none=user),
                _FakeResult(scalar_one_or_none=subscription),
                _FakeResult(scalar_one_or_none=plan),
                _FakeResult(scalar_val=2),  # current channel count
            )
            client = _make_client(mock_db)
            resp = client.post(f"/api/v1/payment-gateway/zoho/subscriptions/validation/{user_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["canCreateChannel"] is True
        assert body["data"]["canCreateMessage"] is None


# ===========================================================================
# POST /zoho/subscriptions/fetchCompanySubscriptionDetails —
# fetch_company_subscription_details
# ===========================================================================

class TestFetchCompanySubscriptionDetails:
    def test_user_not_in_company_403(self, mock_db, admin_user):
        other_company_id = str(_uid())
        client = _make_client(mock_db)
        with _auth(admin_user, "subscription_details_auth"):
            resp = client.post(
                "/api/v1/payment-gateway/zoho/subscriptions/fetchCompanySubscriptionDetails",
                json={"companyId": other_company_id},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 403

    def test_happy_path(self, mock_db, admin_user):
        company_id = admin_user.company_id
        company = _mock_company(id=company_id)
        subscription = _mock_subscription(company_id=company_id, usage_limits=None)
        plan = _mock_plan()
        subscription.plan_id = plan.id
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=company),
            _FakeResult(scalar_one_or_none=subscription),
            _FakeResult(scalar_one_or_none=plan),
            _FakeResult(scalar_val=1),  # admin count
            _FakeResult(scalar_val=4),  # user count
            _FakeResult(scalar_val=2),  # workspace count
            _FakeResult(scalar_val=3),  # channel count
            _FakeResult(all_=[]),  # workspace ids (empty -> ai_response_count stays 0)
            _FakeResult(scalar_val=0),  # attachment size
            _FakeResult(scalar_val=0),  # email attachment size
            _FakeResult(scalar_val=0),  # shared inbox count
            _FakeResult(all_=[subscription]),  # all subscriptions for invoice matching
            _FakeResult(scalar_one_or_none=plan),  # plan lookup inside invoice loop
            _FakeResult(scalar_val=0),  # message count for usage statistics
        )
        zoho_instance = MagicMock()
        zoho_instance.get_customer_invoices = AsyncMock(return_value=[])
        client = _make_client(mock_db)
        with _auth(admin_user, "subscription_details_auth"), _zoho("subscription_details_zoho", zoho_instance):
            resp = client.post(
                "/api/v1/payment-gateway/zoho/subscriptions/fetchCompanySubscriptionDetails",
                json={"companyId": company_id},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["currentPlan"] == plan.name
        assert body["data"]["companyChannelCount"] == 3


# ===========================================================================
# POST /zoho/invoices/companyInvoiceDetails — fetch_company_invoice_details
# ===========================================================================

class TestFetchCompanyInvoiceDetails:
    def test_invalid_company_id_format_400(self, mock_db, regular_user):
        client = _make_client(mock_db)
        with _auth(regular_user, "invoice_details"):
            resp = client.post(
                "/api/v1/payment-gateway/zoho/invoices/companyInvoiceDetails",
                json={"companyId": "not-a-uuid"},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 400

    def test_happy_path_no_active_subscription_returns_empty(self, mock_db, regular_user):
        company_id = str(_uid())
        regular_user.company_id = company_id
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))  # no active subscription
        client = _make_client(mock_db)
        with _auth(regular_user, "invoice_details"):
            resp = client.post(
                "/api/v1/payment-gateway/zoho/invoices/companyInvoiceDetails",
                json={"companyId": company_id},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["invoiceDetails"] == []
        assert body["data"]["totalCost"] is None


# ===========================================================================
# GET /zoho/invoices/{invoice_id}/download — download_invoice
# ===========================================================================

class TestDownloadInvoice:
    def test_no_user_id_in_request_state_401(self, mock_db):
        # with_user_state omitted entirely -> request.state.user_id absent
        client = _make_client(mock_db)
        resp = client.get(
            "/api/v1/payment-gateway/zoho/invoices/inv-001/download",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 401

    def test_happy_path(self, mock_db, admin_user):
        company = _mock_company()
        subscription = _mock_subscription(company_id=company.id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=company),
            _FakeResult(scalar_one_or_none=subscription),
        )
        zoho_instance = MagicMock()
        zoho_instance.get_customer_invoices = AsyncMock(return_value=[{"invoice_id": "inv-001"}])
        zoho_instance.download_invoice_pdf = AsyncMock(return_value=b"%PDF-1.4 fake pdf bytes")
        client = _make_client(mock_db, with_user_state=admin_user.id)
        with (
            _auth(admin_user, "invoice_download"),
            _zoho("invoice_download", zoho_instance),
            patch("app.routes.payment_gateway.invoice_download.get_current_user_required", new=AsyncMock(return_value=admin_user)),
        ):
            resp = client.get(
                "/api/v1/payment-gateway/zoho/invoices/inv-001/download",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.content == b"%PDF-1.4 fake pdf bytes"
        assert resp.headers["content-type"] == "application/pdf"

    def test_ownership_check_403_is_swallowed_bug(self, mock_db, admin_user):
        """Documented pre-existing bug (see module docstring #2): the
        invoice-ownership HTTPException(403) raised inside the inner
        verification try-block is caught by that same block's
        `except Exception as verify_error`, logged as a warning, and
        swallowed — so the download proceeds successfully even though the
        invoice does NOT belong to the customer's invoice list."""
        company = _mock_company()
        subscription = _mock_subscription(company_id=company.id)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=company),
            _FakeResult(scalar_one_or_none=subscription),
        )
        zoho_instance = MagicMock()
        # invoice list does NOT contain "inv-999" -> ownership check should
        # fail, but the bug swallows that failure.
        zoho_instance.get_customer_invoices = AsyncMock(return_value=[{"invoice_id": "inv-001"}])
        zoho_instance.download_invoice_pdf = AsyncMock(return_value=b"%PDF-1.4 other tenant pdf")
        client = _make_client(mock_db, with_user_state=admin_user.id)
        with (
            _zoho("invoice_download", zoho_instance),
            patch("app.routes.payment_gateway.invoice_download.get_current_user_required", new=AsyncMock(return_value=admin_user)),
        ):
            resp = client.get(
                "/api/v1/payment-gateway/zoho/invoices/inv-999/download",
                headers=AUTH_HEADERS,
            )
        # Characterizing the CURRENT (buggy) behavior: this should arguably
        # be a 403, but the code returns 200 with the PDF anyway.
        assert resp.status_code == 200
        assert resp.content == b"%PDF-1.4 other tenant pdf"
