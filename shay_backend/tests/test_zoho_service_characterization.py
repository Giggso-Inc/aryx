"""
Golden-master / characterization tests for app/services/zoho_service.py.

Purpose: zoho_service.py is 1,060 lines (one ZohoBillingService class + a
module-level factory function) with ZERO prior test coverage. It is about to
be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2). Before the
split, we capture the CURRENT observable behavior of the constructor's
platform-config selection, the auth/token-refresh path, the generic
`make_request` dispatcher, and the higher-level customer/subscription/
invoice methods, so the split can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today. No pytest-asyncio is installed, so async
methods are driven with asyncio.run() (matches
tests/test_channels_characterization.py).

Boundary mocking:
- `httpx.AsyncClient` is patched (module path used at call time — see
  CRITICAL GOTCHA note below once split) so no real network call is made.
- `make_request` itself is patched for the higher-level methods that build a
  request body and delegate to it (create_customer, create_subscription*,
  update_subscription, get_subscription(s), get_hosted_page, get_customer*),
  since their interesting behavior is the payload/response shape, not the
  HTTP transport (already covered directly for make_request itself).

Skipped (not characterized), with reason:
- _get_zoho_plan_id(): requires a real/faked AsyncSession generator from
  `app.core.database.get_db` plus a `SubscriptionPlan` model row; the
  "found" and "not found" cases are simple enough (return the scalar or
  None) that faking the whole async-generator DB layer wasn't judged worth
  it for a private helper with no branching beyond that.
- Zoho error-code translation branch in create_subscription_with_customer's
  except clause (checks `hasattr(error, 'response')`): make_request only
  ever raises plain `Exception(str)` (no `.response` attribute), so this
  branch is unreachable through any real caller today — a pre-existing
  dead-code path, not characterized as "working" behavior since it can't
  actually run. Documented, not fixed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


def _svc(platform_name=None):
    from app.services.zoho_service import ZohoBillingService
    return ZohoBillingService(platform_name=platform_name)


# ---------------------------------------------------------------------------
# Constructor / platform config selection
# ---------------------------------------------------------------------------

class TestConstructorConfig:
    def test_default_platform_uses_zoho_prefix(self):
        svc = _svc()
        assert svc._config_prefix == ""
        assert svc.is_prism is False

    def test_prism7_platform_uses_prism_prefix(self):
        svc = _svc("prism7")
        assert svc._config_prefix == "PRISM_"
        assert svc.is_prism is True

    def test_accsell_platform_uses_shay_prefix(self):
        svc = _svc("accsell")
        assert svc._config_prefix == "SHAY_"
        assert svc.is_prism is False

    def test_zaptag_platform_uses_zaptag_prefix(self):
        svc = _svc("zaptag")
        assert svc._config_prefix == "ZAPTAG_"

    def test_unknown_platform_falls_back_to_default(self):
        svc = _svc("some-other-platform")
        assert svc._config_prefix == ""

    def test_get_config_var_name_with_prefix(self):
        svc = _svc("accsell")
        assert svc.get_config_var_name("ZOHO_REFRESH_TOKEN") == "SHAY_ZOHO_REFRESH_TOKEN"

    def test_get_config_var_name_without_prefix(self):
        svc = _svc()
        assert svc.get_config_var_name("ZOHO_REFRESH_TOKEN") == "ZOHO_REFRESH_TOKEN"

    def test_validate_config_warns_on_missing_vars(self, caplog):
        with patch("app.services.zoho_service.config.settings") as mock_settings:
            mock_settings.PRISM_ZOHO_BASE_URL = ""
            mock_settings.PRISM_ZOHO_ORGANIZATION_ID = ""
            mock_settings.PRISM_ZOHO_CLIENT_ID = ""
            mock_settings.PRISM_ZOHO_CLIENT_SECRET = ""
            mock_settings.PRISM_ZOHO_REFRESH_TOKEN = ""
            mock_settings.PRISM_ZOHO_TOKEN_URL = ""
            import logging
            with caplog.at_level(logging.WARNING):
                _svc("prism7")
        assert any("Missing PRISM Zoho configuration" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Auth token / refresh
# ---------------------------------------------------------------------------

class TestAuthToken:
    def test_refresh_auth_token_success(self):
        svc = _svc()
        svc.refresh_token = "rt"
        svc.client_id = "cid"
        svc.client_secret = "secret"
        svc.token_url = "https://token.example/oauth"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "abc123"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cm = MagicMock()
        mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.zoho_service.auth.httpx.AsyncClient", return_value=mock_client_cm):
            token = asyncio.run(svc.refresh_auth_token())
        assert token == "abc123"

    def test_refresh_auth_token_missing_refresh_token_raises(self):
        svc = _svc()
        svc.refresh_token = None
        with pytest.raises(Exception, match="ZOHO_REFRESH_TOKEN"):
            asyncio.run(svc.refresh_auth_token())

    def test_refresh_auth_token_http_error_raises(self):
        svc = _svc()
        svc.refresh_token = "rt"
        svc.client_id = "cid"
        svc.client_secret = "secret"
        svc.token_url = "https://token.example/oauth"

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "bad request"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cm = MagicMock()
        mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.zoho_service.auth.httpx.AsyncClient", return_value=mock_client_cm):
            with pytest.raises(Exception, match="Zoho token refresh failed"):
                asyncio.run(svc.refresh_auth_token())

    def test_get_auth_token_delegates_to_refresh(self):
        svc = _svc()
        with patch.object(svc, "refresh_auth_token", new=AsyncMock(return_value="tok")):
            result = asyncio.run(svc.get_auth_token())
        assert result == "tok"


# ---------------------------------------------------------------------------
# make_request
# ---------------------------------------------------------------------------

class TestMakeRequest:
    def _mock_client(self, response):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=response)
        mock_client.post = AsyncMock(return_value=response)
        mock_client.put = AsyncMock(return_value=response)
        mock_client.delete = AsyncMock(return_value=response)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm, mock_client

    def test_make_request_get_success(self):
        svc = _svc()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"ok": True}
        cm, mock_client = self._mock_client(response)

        with patch.object(svc, "get_auth_token", new=AsyncMock(return_value="tok")), \
             patch("app.services.zoho_service.auth.httpx.AsyncClient", return_value=cm):
            result = asyncio.run(svc.make_request("GET", "/customers"))
        assert result == {"ok": True}
        mock_client.get.assert_called_once()

    def test_make_request_unsupported_method_raises(self):
        svc = _svc()
        with patch.object(svc, "get_auth_token", new=AsyncMock(return_value="tok")), \
             patch("app.services.zoho_service.auth.httpx.AsyncClient"):
            with pytest.raises(ValueError, match="Unsupported HTTP method"):
                asyncio.run(svc.make_request("PATCH", "/x"))

    def test_make_request_error_status_raises(self):
        svc = _svc()
        response = MagicMock()
        response.status_code = 404
        response.text = "not found"
        cm, mock_client = self._mock_client(response)
        with patch.object(svc, "get_auth_token", new=AsyncMock(return_value="tok")), \
             patch("app.services.zoho_service.auth.httpx.AsyncClient", return_value=cm):
            with pytest.raises(Exception, match="Zoho API error: 404"):
                asyncio.run(svc.make_request("GET", "/x"))

    def test_make_request_connect_error_wrapped(self):
        svc = _svc()
        with patch.object(svc, "get_auth_token", new=AsyncMock(return_value="tok")):
            with patch("app.services.zoho_service.auth.httpx.AsyncClient") as mock_cls:
                mock_cls.side_effect = httpx.ConnectError("boom")
                with pytest.raises(Exception, match="Cannot connect to Zoho API"):
                    asyncio.run(svc.make_request("GET", "/x"))


# ---------------------------------------------------------------------------
# format_customer_name
# ---------------------------------------------------------------------------

class TestFormatCustomerName:
    def test_empty_name_returns_empty_string(self):
        svc = _svc()
        assert svc.format_customer_name("") == ""

    def test_strips_special_characters(self):
        svc = _svc()
        assert svc.format_customer_name("John@@ Smith!!") == "John Smith"

    def test_short_name_falls_back_to_original_truncated(self):
        svc = _svc()
        # After stripping special chars, result is < 2 chars -> falls back to name[:50]
        assert svc.format_customer_name("@") == "@"

    def test_long_name_truncated_to_100_chars(self):
        svc = _svc()
        long_name = "A" * 150
        result = svc.format_customer_name(long_name)
        assert len(result) == 100


# ---------------------------------------------------------------------------
# create_customer / get_customers / get_customer
# ---------------------------------------------------------------------------

class TestCustomers:
    def test_create_customer_success(self):
        svc = _svc()
        with patch.object(
            svc, "make_request",
            new=AsyncMock(return_value={"customer": {"customer_id": "c1"}}),
        ) as mock_mr:
            result = asyncio.run(svc.create_customer({"name": "Jane Doe", "email": "jane@example.com"}))
        assert result == {"customer_id": "c1"}
        args, _ = mock_mr.call_args
        assert args[0] == "POST"
        assert args[1] == "/customers"

    def test_create_customer_too_short_name_raises(self):
        svc = _svc()
        with pytest.raises(Exception, match="at least 2 characters"):
            asyncio.run(svc.create_customer({"name": "@"}))

    def test_get_customers_returns_list(self):
        svc = _svc()
        with patch.object(svc, "make_request", new=AsyncMock(return_value={"customers": [{"id": 1}]})):
            result = asyncio.run(svc.get_customers())
        assert result == [{"id": 1}]

    def test_get_customer_returns_empty_dict_when_missing(self):
        svc = _svc()
        with patch.object(svc, "make_request", new=AsyncMock(return_value={})):
            result = asyncio.run(svc.get_customer("c1"))
        assert result == {}


# ---------------------------------------------------------------------------
# create_subscription_with_customer
# ---------------------------------------------------------------------------

class TestCreateSubscriptionWithCustomer:
    def test_uses_existing_customer_when_email_matches(self):
        svc = _svc()
        with patch.object(svc, "get_customers", new=AsyncMock(return_value=[{"email": "jane@example.com", "customer_id": "existing-1"}])), \
             patch.object(svc, "make_request", new=AsyncMock(return_value={"subscription": {"subscription_id": "s1", "customer_id": "existing-1"}})) as mock_mr:
            result = asyncio.run(svc.create_subscription_with_customer({
                "customer": {"email": "jane@example.com", "name": "Jane Doe"},
                "plan": {"planCode": "PLAN1"},
            }))
        assert result["customer_id"] == "existing-1"
        sent_data = mock_mr.call_args[0][2]
        assert sent_data["customer_id"] == "existing-1"

    def test_creates_new_customer_when_no_email_match(self):
        svc = _svc()
        with patch.object(svc, "get_customers", new=AsyncMock(return_value=[])), \
             patch.object(svc, "make_request", new=AsyncMock(return_value={"subscription": {"subscription_id": "s1", "customer_id": "new-1"}})) as mock_mr:
            result = asyncio.run(svc.create_subscription_with_customer({
                "customer": {"email": "new@example.com", "name": "New Person"},
                "plan": {"planCode": "PLAN1"},
            }))
        assert result["customer_id"] == "new-1"
        sent_data = mock_mr.call_args[0][2]
        assert "customer" in sent_data
        assert sent_data["customer"]["email"] == "new@example.com"

    def test_get_customers_lookup_failure_is_swallowed(self):
        # Pre-existing behavior: an error while checking for an existing
        # customer is caught, logged as a warning, and treated as "no
        # existing customer" rather than propagated.
        svc = _svc()
        with patch.object(svc, "get_customers", new=AsyncMock(side_effect=RuntimeError("db down"))), \
             patch.object(svc, "make_request", new=AsyncMock(return_value={"subscription": {"subscription_id": "s1", "customer_id": "new-1"}})) as mock_mr:
            result = asyncio.run(svc.create_subscription_with_customer({
                "customer": {"email": "x@example.com", "name": "X"},
                "plan": {"planCode": "PLAN1"},
            }))
        assert result["customer_id"] == "new-1"


# ---------------------------------------------------------------------------
# create_subscription
# ---------------------------------------------------------------------------

class TestCreateSubscription:
    def test_requires_customer_or_customer_id(self):
        svc = _svc()
        with pytest.raises(ValueError, match="customer.*customerId"):
            asyncio.run(svc.create_subscription({"plan": {"planCode": "P1"}}))

    def test_requires_plan(self):
        svc = _svc()
        with pytest.raises(ValueError, match="'plan' object is required"):
            asyncio.run(svc.create_subscription({"customerId": "c1"}))

    def test_requires_display_name_in_customer_object(self):
        svc = _svc()
        with pytest.raises(ValueError, match="display_name.*displayName"):
            asyncio.run(svc.create_subscription({
                "customer": {"email": "x@example.com"},
                "plan": {"planCode": "P1"},
            }))

    def test_customer_id_path_success(self):
        svc = _svc()
        with patch.object(svc, "make_request", new=AsyncMock(return_value={"subscription": {"subscription_id": "s1"}})) as mock_mr:
            result = asyncio.run(svc.create_subscription({
                "customerId": "c1",
                "plan": {"planCode": "P1"},
            }))
        assert result == {"subscription": {"subscription_id": "s1"}}
        sent_data = mock_mr.call_args[0][2]
        assert sent_data["customer_id"] == "c1"
        assert sent_data["plan"]["plan_code"] == "P1"
        assert sent_data["plan"]["quantity"] == 1  # default quantity

    def test_customer_object_splits_display_name_into_first_last(self):
        svc = _svc()
        with patch.object(svc, "make_request", new=AsyncMock(return_value={"subscription": {}})) as mock_mr:
            asyncio.run(svc.create_subscription({
                "customer": {"displayName": "Jane Doe", "email": "jane@example.com"},
                "plan": {"planCode": "P1"},
            }))
        sent_customer = mock_mr.call_args[0][2]["customer"]
        assert sent_customer["first_name"] == "Jane"
        assert sent_customer["last_name"] == "Doe"

    def test_helpful_error_message_for_plan_code_error(self):
        svc = _svc()
        with patch.object(svc, "make_request", new=AsyncMock(side_effect=Exception("Invalid value passed for Plan Code XYZ"))):
            with pytest.raises(Exception, match="Invalid plan code"):
                asyncio.run(svc.create_subscription({
                    "customerId": "c1",
                    "plan": {"planCode": "BADCODE"},
                }))


# ---------------------------------------------------------------------------
# Hosted pages
# ---------------------------------------------------------------------------

class TestHostedPages:
    def test_create_hosted_page_uses_existing_customer_id(self):
        svc = _svc()
        with patch.object(svc, "make_request", new=AsyncMock(return_value={
            "hostedpage": {"hostedpage_id": "hp1", "url": "https://pay.example/hp1"}
        })) as mock_mr:
            result = asyncio.run(svc.create_hosted_page({
                "zoho_customer_id": "existing-1", "planCode": "P1", "customerEmail": "x@example.com",
            }))
        assert result["hostedPageId"] == "hp1"
        sent_data = mock_mr.call_args[0][2]
        assert sent_data["customer_id"] == "existing-1"
        assert "customer" not in sent_data

    def test_create_hosted_page_builds_new_customer_when_no_id(self):
        svc = _svc()
        with patch.object(svc, "make_request", new=AsyncMock(return_value={"hostedpage": {}})) as mock_mr:
            asyncio.run(svc.create_hosted_page({"customerName": "Jane", "customerEmail": "jane@example.com"}))
        sent_data = mock_mr.call_args[0][2]
        assert sent_data["customer"]["email"] == "jane@example.com"

    def test_get_hosted_page_passthrough(self):
        svc = _svc()
        with patch.object(svc, "make_request", new=AsyncMock(return_value={"hostedpage": {"id": "hp1"}})):
            result = asyncio.run(svc.get_hosted_page("hp1"))
        assert result == {"hostedpage": {"id": "hp1"}}


# ---------------------------------------------------------------------------
# get/update subscription(s)
# ---------------------------------------------------------------------------

class TestSubscriptionCrud:
    def test_get_subscriptions(self):
        svc = _svc()
        with patch.object(svc, "make_request", new=AsyncMock(return_value={"subscriptions": [{"id": 1}]})):
            result = asyncio.run(svc.get_subscriptions())
        assert result == [{"id": 1}]

    def test_get_subscription(self):
        svc = _svc()
        with patch.object(svc, "make_request", new=AsyncMock(return_value={"subscription": {"id": "s1"}})):
            result = asyncio.run(svc.get_subscription("s1"))
        assert result == {"id": "s1"}

    def test_update_subscription_without_plan_change(self):
        svc = _svc()
        with patch.object(svc, "make_request", new=AsyncMock(return_value={"subscription": {"id": "s1"}})) as mock_mr:
            result = asyncio.run(svc.update_subscription("s1", {"autoCollect": True}))
        assert result == {"id": "s1"}
        sent_data = mock_mr.call_args[0][2]
        assert sent_data["auto_collect"] is True
        assert "plan" not in sent_data


# ---------------------------------------------------------------------------
# cancel / reactivate subscription (bypass make_request, own httpx call)
# ---------------------------------------------------------------------------

class TestCancelReactivate:
    def _mock_client(self, response):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=response)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm, mock_client

    def test_cancel_subscription_sends_cancel_at_end_query_param(self):
        svc = _svc()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"subscription": {"status": "non_renewing"}}
        cm, mock_client = self._mock_client(response)
        with patch.object(svc, "get_auth_token", new=AsyncMock(return_value="tok")), \
             patch("app.services.zoho_service.subscriptions.httpx.AsyncClient", return_value=cm):
            result = asyncio.run(svc.cancel_subscription("s1", cancel_at_end=True))
        assert result == {"subscription": {"status": "non_renewing"}}
        _, kwargs = mock_client.post.call_args
        assert kwargs["params"] == {"cancel_at_end": "true"}

    def test_reactivate_subscription_sends_billing_cycles_query_param(self):
        svc = _svc()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"subscription": {"status": "active"}}
        cm, mock_client = self._mock_client(response)
        with patch.object(svc, "get_auth_token", new=AsyncMock(return_value="tok")), \
             patch("app.services.zoho_service.subscriptions.httpx.AsyncClient", return_value=cm):
            result = asyncio.run(svc.reactivate_subscription("s1", billing_cycles=6))
        assert result == {"subscription": {"status": "active"}}
        _, kwargs = mock_client.post.call_args
        assert kwargs["params"] == {"billing_cycles": 6}


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

class TestInvoices:
    def test_get_customer_invoices_success(self):
        svc = _svc()
        with patch.object(svc, "make_request", new=AsyncMock(return_value={"invoices": [{"id": "i1"}]})):
            result = asyncio.run(svc.get_customer_invoices("c1"))
        assert result == [{"id": "i1"}]

    def test_get_customer_invoices_swallows_error_returns_empty_list(self):
        svc = _svc()
        with patch.object(svc, "make_request", new=AsyncMock(side_effect=RuntimeError("boom"))):
            result = asyncio.run(svc.get_customer_invoices("c1"))
        assert result == []

    def test_get_invoice_success(self):
        svc = _svc()
        with patch.object(svc, "make_request", new=AsyncMock(return_value={"invoice": {"id": "i1"}})):
            result = asyncio.run(svc.get_invoice("i1"))
        assert result == {"id": "i1"}

    def test_download_invoice_pdf_success(self):
        svc = _svc()
        response = MagicMock()
        response.status_code = 200
        response.content = b"%PDF-1.4 fake"
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=response)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=False)
        with patch.object(svc, "get_auth_token", new=AsyncMock(return_value="tok")), \
             patch("app.services.zoho_service.invoices.httpx.AsyncClient", return_value=cm):
            result = asyncio.run(svc.download_invoice_pdf("i1"))
        assert result == b"%PDF-1.4 fake"

    def test_download_invoice_pdf_error_status_raises(self):
        svc = _svc()
        response = MagicMock()
        response.status_code = 404
        response.text = "not found"
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=response)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_client)
        cm.__aexit__ = AsyncMock(return_value=False)
        with patch.object(svc, "get_auth_token", new=AsyncMock(return_value="tok")), \
             patch("app.services.zoho_service.invoices.httpx.AsyncClient", return_value=cm):
            with pytest.raises(Exception, match="Zoho API error: 404"):
                asyncio.run(svc.download_invoice_pdf("i1"))


# ---------------------------------------------------------------------------
# get_zoho_service factory
# ---------------------------------------------------------------------------

class TestGetZohoServiceFactory:
    def test_returns_module_singleton_for_none(self):
        from app.services.zoho_service import get_zoho_service, zoho_service
        assert get_zoho_service(None) is zoho_service

    def test_returns_module_singleton_for_unknown_platform(self):
        from app.services.zoho_service import get_zoho_service, zoho_service
        assert get_zoho_service("unknown-platform") is zoho_service

    def test_returns_new_instance_for_known_platform(self):
        from app.services.zoho_service import get_zoho_service, zoho_service
        result = get_zoho_service("accsell")
        assert result is not zoho_service
        assert result._config_prefix == "SHAY_"

    def test_platform_name_is_case_insensitive(self):
        from app.services.zoho_service import get_zoho_service
        result = get_zoho_service("PRISM7")
        assert result._config_prefix == "PRISM_"
