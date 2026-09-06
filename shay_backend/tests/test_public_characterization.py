"""
Golden-master / characterization tests for app/routes/public.py.

Purpose: this file (2,196 lines, 15 endpoints) has zero existing test
coverage and is about to be split into smaller modules (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5). Before the split,
we capture the CURRENT observable behavior of every endpoint so the split
can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included.

Pattern follows tests/test_datasources_characterization.py exactly:
- FastAPI TestClient with `app.include_router(router, prefix=...)`.
- `app.dependency_overrides[get_db] = lambda: mock_db`.
- MagicMock/AsyncMock for services; no real DB, no real HTTP.
- asyncio.run() is not needed here since TestClient drives the async
  endpoints itself; used only where we call helpers directly.

Do not modify app/routes/public.py from this file's tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(mock_db):
    from app.core.database import get_db
    from app.routes.public import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/public")
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app, raise_server_exceptions=False)


class _FakeResult:
    """Mimics the subset of SQLAlchemy's async Result API used by public.py:
    .scalar_one_or_none(), .scalars().all(), .fetchone(), .scalar()."""

    def __init__(self, scalar_one_or_none=None, all_=None, scalar_val=None, fetchone_val=None):
        self._son = scalar_one_or_none
        self._all = all_ if all_ is not None else []
        self._scalar_val = scalar_val
        self._fetchone = fetchone_val

    def scalar_one_or_none(self):
        return self._son

    def scalars(self):
        m = MagicMock()
        m.all = MagicMock(return_value=self._all)
        m.first = MagicMock(return_value=self._all[0] if self._all else None)
        return m

    def fetchone(self):
        return self._fetchone

    def scalar(self):
        return self._scalar_val


def _exec_seq(*results):
    return AsyncMock(side_effect=list(results))


def _mock_company(**overrides):
    c = MagicMock()
    c.id = "company-001"
    c.name = "Test Co"
    c.domain = "example.com"
    c.is_active = True
    c.settings = {}
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


def _mock_user(**overrides):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.email_id = "user@example.com"
    u.role = "admin"
    u.company_id = "company-001"
    u.is_active = True
    u.is_verified = True
    u.name = "Test User"
    u.password_hash = "hashed"
    u.avatar_url = None
    u.company = _mock_company()
    for k, v in overrides.items():
        setattr(u, k, v)
    return u


def _mock_plan(**overrides):
    from decimal import Decimal
    p = MagicMock()
    p.id = uuid.uuid4()
    p.name = "Free"
    p.plan_code = "free"
    p.description = "Free plan"
    p.monthly_price = Decimal("0.00")
    p.plan_cycles = 1
    p.features = []
    p.is_active = True
    p.sort_order = 0
    p.created_at = datetime.utcnow()
    p.updated_at = datetime.utcnow()
    p.zoho_plan_id = None
    p.zoho_product_id = None
    p.interval_count = 1
    p.zoho_plan_code = None
    p.zoho_product_code = None
    p.zoho_billing_cycle = None
    p.interval_unit = "months"
    p.interval = 1
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def _mock_subscription(**overrides):
    from decimal import Decimal
    s = MagicMock()
    s.id = uuid.uuid4()
    s.company_id = "company-001"
    s.plan_id = uuid.uuid4()
    s.status = "active"
    s.subscription_status = "active"
    s.zoho_customer_id = None
    s.zoho_subscription_id = None
    s.zoho_cancel_at_period_end = False
    s.current_period_end = datetime.utcnow()
    s.created_at = datetime.utcnow()
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ===========================================================================
# POST /createCompany
# ===========================================================================

class TestCreateCompany:
    def _payload(self, **overrides):
        payload = {
            "company": {"name": "Acme", "domain": "acme.com"},
            "user": {"email": "admin@acme.com", "password": "secret123"},
        }
        payload.update(overrides)
        return payload

    @pytest.mark.unit
    def test_happy_path_actually_500s_due_to_username_attribute_bug(self, mock_db):
        """Pre-existing defect: CompanyCreate has no `userName` field (only
        CompanyCreateSimple does), but create_company unconditionally reads
        `company_data.userName` when building the admin User row. Every
        non-conflicting call to this endpoint therefore 500s today."""
        plan = _mock_plan()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=None),  # domain check (no existing company)
            _FakeResult(scalar_one_or_none=None),  # existing user check
            _FakeResult(scalar_one_or_none=plan),  # default plan lookup
        )
        client = _make_client(mock_db)
        resp = client.post("/api/v1/public/createCompany", json=self._payload())
        assert resp.status_code == 500
        assert "userName" in resp.json()["detail"]

    @pytest.mark.unit
    def test_domain_conflict_returns_409(self, mock_db):
        existing_company = _mock_company(is_active=True)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=existing_company))
        client = _make_client(mock_db)
        resp = client.post("/api/v1/public/createCompany", json=self._payload())
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]


# ===========================================================================
# POST /companies
# ===========================================================================

class TestCreateCompanySimple:
    def _payload(self, **overrides):
        payload = {
            "name": "Acme",
            "domain": "acme.com",
            "contactEmail": "admin@acme.com",
            "userName": "Admin",
            "password": "secret123",
        }
        payload.update(overrides)
        return payload

    @pytest.mark.unit
    def test_happy_path_creates_company(self, mock_db):
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=None),  # domain check
            _FakeResult(scalar_one_or_none=None),  # existing user check
        )
        with patch(
            "app.routes.public.signup_create_simple_email.email_verification_service.generate_verification_token",
            new=AsyncMock(return_value=MagicMock(token="tok-123")),
        ), patch(
            "app.routes.public.signup_create_simple_email.email_verification_service.send_verification_email",
            new=AsyncMock(return_value=True),
        ):
            client = _make_client(mock_db)
            resp = client.post("/api/v1/public/companies", json=self._payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["companyName"] == "Acme"
        # Zoho and subscription creation are commented out in current code.
        assert body["data"]["planId"] is None
        assert body["data"]["planName"] is None

    @pytest.mark.unit
    def test_domain_conflict_active_company_returns_409(self, mock_db):
        existing_company = _mock_company(is_active=True)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=existing_company))
        client = _make_client(mock_db)
        resp = client.post("/api/v1/public/companies", json=self._payload())
        assert resp.status_code == 409


# ===========================================================================
# DELETE /companies/{company_id}
# ===========================================================================

class TestDeleteCompany:
    @pytest.mark.unit
    def test_soft_delete_happy_path(self, mock_db):
        company = _mock_company(is_active=True)
        user = _mock_user()
        sub = _mock_subscription()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=company),
            _FakeResult(all_=[user]),
            _FakeResult(all_=[sub]),
        )
        client = _make_client(mock_db)
        resp = client.delete("/api/v1/public/companies/company-001")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["companyStatus"] == "inactive"
        assert body["data"]["deactivatedUsersCount"] == 1

    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        resp = client.delete("/api/v1/public/companies/missing")
        assert resp.status_code == 404


# ===========================================================================
# DELETE /companies/domain/{domain}
# ===========================================================================

class TestDeleteCompanyByDomain:
    @pytest.mark.unit
    def test_already_inactive_returns_400(self, mock_db):
        company = _mock_company(is_active=False)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=company))
        client = _make_client(mock_db)
        resp = client.delete("/api/v1/public/companies/domain/acme.com")
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        resp = client.delete("/api/v1/public/companies/domain/missing.com")
        assert resp.status_code == 404


# ===========================================================================
# PATCH /companies/{company_id}/reactivate
# ===========================================================================

class TestReactivateCompany:
    @pytest.mark.unit
    def test_happy_path(self, mock_db):
        company = _mock_company(is_active=False)
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=company),
            _FakeResult(all_=[]),
            _FakeResult(all_=[]),
        )
        client = _make_client(mock_db)
        resp = client.patch("/api/v1/public/companies/company-001/reactivate")
        assert resp.status_code == 200
        assert resp.json()["data"]["companyStatus"] == "active"

    @pytest.mark.unit
    def test_already_active_returns_400(self, mock_db):
        company = _mock_company(is_active=True)
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=company))
        client = _make_client(mock_db)
        resp = client.patch("/api/v1/public/companies/company-001/reactivate")
        assert resp.status_code == 400


# ===========================================================================
# PATCH /companies/domain/{domain}/reactivate
# ===========================================================================

class TestReactivateCompanyByDomain:
    @pytest.mark.unit
    def test_not_found_returns_404(self, mock_db):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        resp = client.patch("/api/v1/public/companies/domain/missing.com/reactivate")
        assert resp.status_code == 404


# ===========================================================================
# GET /fetchPlans
# ===========================================================================

class TestFetchPlans:
    @pytest.mark.unit
    def test_returns_cleaned_plans(self, mock_db):
        plan = _mock_plan()
        mock_db.execute = _exec_seq(_FakeResult(all_=[plan]))
        client = _make_client(mock_db)
        resp = client.get("/api/v1/public/fetchPlans")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) == 1
        assert body["data"][0]["planCode"] == "free"

    @pytest.mark.unit
    def test_filters_by_platform_name(self, mock_db):
        mock_db.execute = _exec_seq(_FakeResult(all_=[]))
        client = _make_client(mock_db)
        resp = client.get("/api/v1/public/fetchPlans?platform_name=prism7")
        assert resp.status_code == 200
        assert resp.json()["data"] == []


# ===========================================================================
# POST /autoLogin
# ===========================================================================

class TestAutoLogin:
    @pytest.mark.unit
    def test_user_not_found_returns_404(self, mock_db):
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))
        client = _make_client(mock_db)
        resp = client.post("/api/v1/public/autoLogin?email=x@x.com&password=pw")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_happy_path_returns_tokens(self, mock_db):
        user = _mock_user(password_hash="hashed-pw")
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=user))
        with patch("app.routes.public.auth.verify_password", return_value=True):
            client = _make_client(mock_db)
            resp = client.post(
                "/api/v1/public/autoLogin",
                params={"email": user.email_id, "password": "pw"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["user_id"] == str(user.id)


# ===========================================================================
# GET /mySubscription
# ===========================================================================

class TestMySubscription:
    @pytest.mark.unit
    def test_missing_auth_header_returns_401(self, mock_db):
        client = _make_client(mock_db)
        resp = client.get("/api/v1/public/mySubscription")
        assert resp.status_code == 401

    @pytest.mark.unit
    def test_happy_path(self, mock_db):
        subscription = _mock_subscription()
        plan = _mock_plan()
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=subscription),
            _FakeResult(scalar_one_or_none=plan),
        )
        with patch(
            "app.routes.public.subscription.decode_access_token",
            return_value={"company_id": "company-001"},
        ):
            client = _make_client(mock_db)
            resp = client.get(
                "/api/v1/public/mySubscription",
                headers={"Authorization": "Bearer faketoken"},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["planCode"] == "free"


# ===========================================================================
# POST /createUser
# ===========================================================================

class TestCreateUser:
    @pytest.mark.unit
    def test_missing_fields_returns_400(self, mock_db):
        client = _make_client(mock_db)
        resp = client.post("/api/v1/public/createUser", json={"email": "a@b.com"})
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_happy_path(self, mock_db):
        company = _mock_company()
        created_user = _mock_user(email_id="new@acme.com", role="customer")
        mock_db.execute = _exec_seq(
            _FakeResult(scalar_one_or_none=company),
            _FakeResult(scalar_one_or_none=None),
            _FakeResult(scalar_one_or_none=created_user),
        )
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/public/createUser",
            json={"email": "new@acme.com", "password": "pw123456", "companyId": "company-001"},
        )
        # No explicit @router status_code, so the actual HTTP status is 200
        # even though the response body's "code" field says 201.
        assert resp.status_code == 200
        assert resp.json()["code"] == 201
        assert resp.json()["data"]["email"] == "new@acme.com"


# ===========================================================================
# GET /zoho/access-token
# ===========================================================================

class TestZohoAccessToken:
    @pytest.mark.unit
    def test_missing_refresh_token_returns_400(self, mock_db):
        fake_svc = MagicMock()
        fake_svc.refresh_token = None
        fake_svc.get_config_var_name = MagicMock(return_value="ZOHO_REFRESH_TOKEN")
        with patch("app.routes.public.zoho.get_zoho_service", return_value=fake_svc):
            client = _make_client(mock_db)
            resp = client.get("/api/v1/public/zoho/access-token")
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_happy_path(self, mock_db):
        fake_svc = MagicMock()
        fake_svc.refresh_token = "rt"
        fake_svc.client_id = "id"
        fake_svc.client_secret = "secret"
        fake_svc.token_url = "https://zoho/token"
        fake_svc.refresh_auth_token = AsyncMock(return_value="access-token-value")
        with patch("app.routes.public.zoho.get_zoho_service", return_value=fake_svc):
            client = _make_client(mock_db)
            resp = client.get("/api/v1/public/zoho/access-token")
        assert resp.status_code == 200
        assert resp.json()["data"]["access_token"] == "access-token-value"


# ===========================================================================
# POST /verify-email
# ===========================================================================

class TestVerifyEmail:
    @pytest.mark.unit
    def test_happy_path(self, mock_db):
        company = _mock_company()
        user = _mock_user()
        mock_db.execute = _exec_seq(_FakeResult(scalar_one_or_none=None))  # workspace lookup
        with patch(
            "app.routes.public.verify_email.email_verification_service.verify_token",
            new=AsyncMock(return_value=(company, user)),
        ):
            client = _make_client(mock_db)
            resp = client.post("/api/v1/public/verify-email", json={"token": "tok"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["company_id"] == str(company.id)

    @pytest.mark.unit
    def test_invalid_token_returns_500(self, mock_db):
        with patch(
            "app.routes.public.verify_email.email_verification_service.verify_token",
            new=AsyncMock(side_effect=ValueError("bad token")),
        ):
            client = _make_client(mock_db)
            resp = client.post("/api/v1/public/verify-email", json={"token": "bad"})
        assert resp.status_code == 500


# ===========================================================================
# POST /resend-verification
# ===========================================================================

class TestResendVerification:
    @pytest.mark.unit
    def test_already_verified_returns_success_no_email(self, mock_db):
        with patch(
            "app.routes.public.resend_verification.email_verification_service.resend_verification",
            new=AsyncMock(return_value=None),
        ):
            client = _make_client(mock_db)
            resp = client.post(
                "/api/v1/public/resend-verification", json={"email": "a@b.com"}
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["email_sent"] is False
        assert "already verified" in body["message"]

    @pytest.mark.unit
    def test_email_sent_true(self, mock_db):
        with patch(
            "app.routes.public.resend_verification.email_verification_service.resend_verification",
            new=AsyncMock(return_value=True),
        ):
            client = _make_client(mock_db)
            resp = client.post(
                "/api/v1/public/resend-verification", json={"email": "a@b.com"}
            )
        assert resp.status_code == 200
        assert resp.json()["email_sent"] is True


# ===========================================================================
# POST /notify-api-failure
# ===========================================================================

class TestNotifyApiFailure:
    @pytest.mark.unit
    def test_happy_path(self, mock_db):
        with patch(
            "app.routes.public.notifications.email_service.send_error_notification_email",
            return_value=True,
        ):
            client = _make_client(mock_db)
            resp = client.post(
                "/api/v1/public/notify-api-failure",
                json={"api_endpoint": "/x", "error_message": "boom"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["email_sent"] is True

    @pytest.mark.unit
    def test_email_send_failure_returns_success_false(self, mock_db):
        with patch(
            "app.routes.public.notifications.email_service.send_error_notification_email",
            return_value=False,
        ):
            client = _make_client(mock_db)
            resp = client.post(
                "/api/v1/public/notify-api-failure",
                json={"api_endpoint": "/x", "error_message": "boom"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ===========================================================================
# POST /saveTokenDetails
# ===========================================================================

class TestSaveTokenDetails:
    def _payload(self, **overrides):
        payload = {
            "token_type": "openai",
            "tokenName": "my-token",
            "api_key": "sk-abc",
            "embedding_model": "text-embedding-3",
            "gpt_model": "gpt-4",
            "companyId": str(uuid.uuid4()),
        }
        payload.update(overrides)
        return payload

    @pytest.mark.unit
    def test_invalid_company_id_returns_400(self, mock_db):
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/public/saveTokenDetails", json=self._payload(companyId="not-a-uuid")
        )
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_happy_path(self, mock_db):
        vault_record = MagicMock()
        vault_record.giggso_vault_id = uuid.uuid4()

        def _refresh_side_effect(obj):
            obj.giggso_vault_id = vault_record.giggso_vault_id

        mock_db.refresh = AsyncMock(side_effect=_refresh_side_effect)
        with patch(
            "app.routes.public.vault.vault_service.generate_vault_unique_id",
            return_value="vault/unique/id",
        ), patch(
            "app.routes.public.vault.vault_service.save_to_vault",
            new=AsyncMock(return_value="saved-id"),
        ):
            client = _make_client(mock_db)
            resp = client.post("/api/v1/public/saveTokenDetails", json=self._payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["vault_unique_id"] == "vault/unique/id"

    @pytest.mark.unit
    def test_azure_missing_fields_returns_400(self, mock_db):
        client = _make_client(mock_db)
        resp = client.post(
            "/api/v1/public/saveTokenDetails", json=self._payload(token_type="azure")
        )
        assert resp.status_code == 400
        assert "deploymentName" in resp.json()["detail"]
