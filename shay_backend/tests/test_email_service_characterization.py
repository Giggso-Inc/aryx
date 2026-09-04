"""
Golden-master / characterization tests for app/services/email_service.py.

Purpose: email_service.py is 1,821 lines (one EmailService class + a module
singleton) with ZERO prior test coverage. It is about to be split into a
package (see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
Before the split, we capture the CURRENT observable behavior of every public
send_* method (and a few load-bearing private helpers) so the split can be
verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included (documented inline where
found). No pytest-asyncio is installed, so async methods are driven with
asyncio.run() (matches tests/test_channels_characterization.py).

Boundary mocking:
- `_send_email` (the only method that actually talks to SMTP) is patched on
  every test that would otherwise reach the network.
- `template_service.get_template_content` / real HTML templates on disk
  (templates/email/*.html) are used as-is where the code reads real files
  (fast, deterministic, no network) — this matches how these methods behave
  in production for the "template found" branch.

Skipped (not characterized), with reason:
- test_connection() / test_email_sending(): thin diagnostic wrappers around
  _send_email with no branching logic beyond what send_password_reset_email
  already exercises for _send_email's own branches; would require a live/faked
  SMTP socket to add real value beyond what's already covered.
- Deeply-nested HTML string content (exact pixel/markup diffing) is not
  asserted line-by-line; tests assert on the presence of key interpolated
  values (names, links, ticket refs) which is what matters for the split.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _svc():
    from app.services.email_service import EmailService
    return EmailService()


# ---------------------------------------------------------------------------
# _send_email / SMTP boundary
# ---------------------------------------------------------------------------

class TestSendEmail:
    def test_send_email_success(self):
        svc = _svc()
        with patch("app.services.email_service.core.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value = mock_server
            svc.username = "user"
            svc.password = "pass"
            from email.mime.text import MIMEText
            msg = MIMEText("body")
            msg["To"] = "to@example.com"
            result = svc._send_email(msg)
        assert result is True
        mock_server.sendmail.assert_called_once()
        mock_server.quit.assert_called_once()

    def test_send_email_auth_failure_returns_false(self):
        import smtplib
        svc = _svc()
        with patch("app.services.email_service.core.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad creds")
            mock_smtp_cls.return_value = mock_server
            svc.username = "user"
            svc.password = "pass"
            from email.mime.text import MIMEText
            msg = MIMEText("body")
            msg["To"] = "to@example.com"
            result = svc._send_email(msg)
        assert result is False
        mock_server.quit.assert_called_once()

    def test_send_email_no_credentials_still_sends(self):
        svc = _svc()
        svc.username = None
        svc.password = None
        with patch("app.services.email_service.core.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value = mock_server
            from email.mime.text import MIMEText
            msg = MIMEText("body")
            msg["To"] = "to@example.com"
            result = svc._send_email(msg)
        assert result is True
        mock_server.login.assert_not_called()


# ---------------------------------------------------------------------------
# Invitation emails
# ---------------------------------------------------------------------------

class TestInvitationEmails:
    def test_send_invitation_email_success(self):
        svc = _svc()
        with patch.object(svc, "_send_email", return_value=True) as mock_send:
            result = svc.send_invitation_email(
                "to@example.com",
                {
                    "email": "to@example.com",
                    "user_name": "jane.doe",
                    "invited_by": "john.smith",
                    "company_name": "Acme",
                    "registration_link": "https://x.test/reg",
                },
            )
        assert result is True
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert msg["Subject"] == "Invitation to join Aryx"

    def test_send_invitation_email_send_failure_returns_false(self):
        svc = _svc()
        with patch.object(svc, "_send_email", return_value=False):
            result = svc.send_invitation_email("to@example.com", {"email": "to@example.com"})
        assert result is False

    def test_send_invitation_email_exception_returns_false(self):
        svc = _svc()
        with patch.object(svc, "_send_email", side_effect=RuntimeError("boom")):
            result = svc.send_invitation_email("to@example.com", {"email": "to@example.com"})
        assert result is False

    def test_send_bulk_invitation_emails_partial_failure(self):
        svc = _svc()
        calls = {"n": 0}

        def fake_send(email_id, data, url):
            calls["n"] += 1
            return calls["n"] == 1  # first succeeds, second fails

        with patch.object(svc, "send_invitation_email", side_effect=fake_send):
            result = svc.send_bulk_invitation_emails(
                [
                    {"email_id": "a@example.com"},
                    {"email_id": "b@example.com"},
                ]
            )
        assert result["successful"] == ["a@example.com"]
        assert result["failed"] == [{"email": "b@example.com", "reason": "Email sending failed"}]

    def test_send_bulk_invitation_emails_exception_captured_per_item(self):
        svc = _svc()
        with patch.object(svc, "send_invitation_email", side_effect=ValueError("bad")):
            result = svc.send_bulk_invitation_emails([{"email_id": "a@example.com"}])
        assert result["successful"] == []
        assert result["failed"] == [{"email": "a@example.com", "reason": "bad"}]

    def test_send_template_invitation_email_default_template_used(self):
        svc = _svc()
        with patch.object(svc, "_send_email", return_value=True) as mock_send:
            result = asyncio.run(
                svc.send_template_invitation_email(
                    "to@example.com",
                    {"email": "to@example.com", "user_name": "Jane"},
                )
            )
        assert result is True
        mock_send.assert_called_once()

    def test_resolve_user_name_prefers_explicit_name(self):
        svc = _svc()
        assert svc._resolve_user_name({"user_name": "jane-doe", "email": "x@y.com"}) == "Jane Doe"

    def test_resolve_user_name_falls_back_to_email_local_part(self):
        svc = _svc()
        assert svc._resolve_user_name({"email": "john.smith@example.com"}) == "John Smith"

    def test_resolve_user_name_falls_back_to_default(self):
        svc = _svc()
        assert svc._resolve_user_name({}) == "There"


# ---------------------------------------------------------------------------
# Password reset emails
# ---------------------------------------------------------------------------

class TestPasswordResetEmails:
    def test_send_password_reset_email_success(self):
        svc = _svc()
        with patch.object(svc, "_send_email", return_value=True):
            result = svc.send_password_reset_email(
                "to@example.com",
                {"user_name": "Jane", "reset_url": "https://x.test/reset", "email": "to@example.com"},
            )
        assert result is True

    def test_send_password_reset_email_missing_template_file_raises_and_is_caught(self):
        # _create_password_reset_html re-raises FileNotFoundError when the
        # template load fails a second time; send_password_reset_email's
        # try/except around the whole flow swallows it and returns False.
        svc = _svc()
        with patch.object(svc, "_load_template", side_effect=FileNotFoundError("missing")):
            result = svc.send_password_reset_email("to@example.com", {"email": "to@example.com"})
        assert result is False

    def test_send_template_password_reset_email_requires_template_id_and_db(self):
        svc = _svc()
        result = asyncio.run(
            svc.send_template_password_reset_email("to@example.com", {"email": "to@example.com"})
        )
        # ValueError raised internally for missing template_id/db, caught by
        # the method's own except-Exception, returns False (current behavior).
        assert result is False

    def test_send_template_password_reset_email_with_template_id_and_db_always_false(self):
        # Pre-existing bug: _create_password_reset_text is called with 4
        # positional args here but only accepts 2 -> TypeError, swallowed by
        # this method's own broad except -> always False on this path, even
        # though a valid template_id/db were supplied and the template loads
        # fine. Characterizing current (buggy) behavior, not fixing it.
        svc = _svc()
        db = MagicMock()
        with patch(
            "app.services.email_service.password_reset.template_service.get_template_content",
            new=AsyncMock(return_value={"content": "hello {user_name}"}),
        ):
            result = asyncio.run(
                svc.send_template_password_reset_email(
                    "to@example.com",
                    {"email": "to@example.com", "reset_url": "https://x.test/reset"},
                    template_id="tmpl-1",
                    db=db,
                )
            )
        assert result is False


# ---------------------------------------------------------------------------
# Verification emails
# ---------------------------------------------------------------------------

class TestVerificationEmails:
    def test_send_verification_email_success(self):
        svc = _svc()
        with patch.object(svc, "_send_email", return_value=True):
            result = svc.send_verification_email(
                "to@example.com",
                {"company_name": "Acme", "user_name": "Jane", "verification_link": "https://x.test/v"},
            )
        assert result is True

    def test_send_verification_email_send_failure(self):
        svc = _svc()
        with patch.object(svc, "_send_email", return_value=False):
            result = svc.send_verification_email("to@example.com", {})
        assert result is False


# ---------------------------------------------------------------------------
# Workspace access emails (async)
# ---------------------------------------------------------------------------

class TestWorkspaceAccessEmails:
    def test_send_workspace_access_email_success(self):
        svc = _svc()
        with patch.object(svc, "_send_email", return_value=True):
            result = asyncio.run(
                svc.send_workspace_access_email(
                    "to@example.com",
                    {"workspace_name": "Acme WS", "user_name": "Jane", "role": "member", "added_by": "Admin"},
                )
            )
        assert result is True

    def test_send_workspace_access_email_exception_returns_false(self):
        svc = _svc()
        with patch.object(svc, "_send_email", side_effect=RuntimeError("smtp down")):
            result = asyncio.run(svc.send_workspace_access_email("to@example.com", {}))
        assert result is False


# ---------------------------------------------------------------------------
# Welcome emails
# ---------------------------------------------------------------------------

class TestWelcomeEmails:
    def test_send_welcome_email_success(self):
        svc = _svc()
        with patch.object(svc, "_send_email", return_value=True):
            result = svc.send_welcome_email(
                {"companyName": "Acme", "contactEmail": "to@example.com", "planName": "Pro", "monthlyPrice": 99}
            )
        assert result["success"] is True
        assert "messageId" in result

    def test_send_welcome_email_missing_required_fields(self):
        svc = _svc()
        result = svc.send_welcome_email({})
        assert result["success"] is False
        assert "companyName" in result["error"]

    def test_send_welcome_email_smtp_failure(self):
        svc = _svc()
        with patch.object(svc, "_send_email", return_value=False):
            result = svc.send_welcome_email({"companyName": "Acme", "contactEmail": "to@example.com"})
        assert result["success"] is False
        assert result["error"] == "Failed to send email via SMTP"


# ---------------------------------------------------------------------------
# Channel member notification
# ---------------------------------------------------------------------------

class TestChannelMemberNotification:
    def test_no_recipients_returns_true_without_sending(self):
        svc = _svc()
        with patch.object(svc, "_send_email") as mock_send:
            result = svc.send_channel_member_notification([], {})
        assert result is True
        mock_send.assert_not_called()

    def test_admin_branch_subject(self):
        svc = _svc()
        with patch.object(svc, "_send_email", return_value=True) as mock_send:
            result = svc.send_channel_member_notification(
                ["admin@example.com"],
                {"channel_name": "general", "user_name": "Jane"},
            )
        assert result is True
        msg = mock_send.call_args[0][0]
        assert msg["Subject"] == "New User Added to Channel - general"

    def test_added_user_branch_subject(self):
        svc = _svc()
        with patch.object(svc, "_send_email", return_value=True) as mock_send:
            result = svc.send_channel_member_notification(
                ["user@example.com"],
                {"channel_name": "general", "user_name": "Jane", "send_to_added_user": True},
            )
        assert result is True
        msg = mock_send.call_args[0][0]
        assert msg["Subject"] == "You have been added to channel - general"

    def test_added_user_flag_accepts_string_true(self):
        svc = _svc()
        assert svc._is_send_to_added_user({"send_to_added_user": "true"}) is True
        assert svc._is_send_to_added_user({"send_to_added_user": "1"}) is True
        assert svc._is_send_to_added_user({"send_to_added_user": 1}) is True
        assert svc._is_send_to_added_user({"send_to_added_user": False}) is False
        assert svc._is_send_to_added_user({}) is False

    def test_all_recipients_must_succeed_for_true(self):
        svc = _svc()
        with patch.object(svc, "_send_email", side_effect=[True, False]):
            result = svc.send_channel_member_notification(
                ["a@example.com", "b@example.com"], {"channel_name": "general"}
            )
        assert result is False


# ---------------------------------------------------------------------------
# Error notification email
# ---------------------------------------------------------------------------

class TestErrorNotificationEmail:
    def test_send_error_notification_email_success(self):
        svc = _svc()
        with patch.object(svc, "_send_email", return_value=True) as mock_send:
            result = svc.send_error_notification_email(
                "support@example.com",
                {"api_endpoint": "/api/v1/x", "error_message": "boom"},
            )
        assert result is True
        msg = mock_send.call_args[0][0]
        assert msg["Subject"] == "API Failure Alert - /api/v1/x"

    def test_truncates_long_error_message(self):
        svc = _svc()
        long_msg = "x" * 600
        html = svc._create_error_notification_html(
            {"api_endpoint": "/x", "error_message": long_msg}, "http://localhost:3000"
        )
        assert "(truncated)" in html


# ---------------------------------------------------------------------------
# Support request / confirmation emails
# ---------------------------------------------------------------------------

class TestSupportEmails:
    def test_send_support_request_email_success(self):
        svc = _svc()
        with patch.object(svc, "_send_email", return_value=True) as mock_send:
            result = svc.send_support_request_email(
                "support@example.com",
                {"name": "Jane", "email": "jane@example.com", "ticket_reference": "T-1", "description": "help"},
            )
        assert result is True
        msg = mock_send.call_args[0][0]
        assert "T-1" in msg["Subject"]

    def test_send_support_confirmation_email_success(self):
        svc = _svc()
        with patch.object(svc, "_send_email", return_value=True) as mock_send:
            result = svc.send_support_confirmation_email(
                "jane@example.com", {"name": "Jane", "ticket_reference": "T-1"}
            )
        assert result is True
        msg = mock_send.call_args[0][0]
        assert "T-1" in msg["Subject"]

    def test_replace_placeholders_orders_by_key_length(self):
        svc = _svc()
        out = svc._replace_placeholders("{a}{ab}", {"a": "1", "ab": "2"})
        # Longest key replaced first so {ab} isn't mangled by a naive {a} replace.
        assert out == "12"


# ---------------------------------------------------------------------------
# Logo / branding helpers
# ---------------------------------------------------------------------------

class TestBrandingHelpers:
    def test_get_platform_logo_url_only_for_accsell_and_zaptag(self):
        svc = _svc()
        assert svc._get_platform_logo_url("prism7") is None
        assert svc._get_platform_logo_url(None) is None

    def test_is_public_logo_url(self):
        svc = _svc()
        assert svc._is_public_logo_url("https://x.test/logo.png") is True
        assert svc._is_public_logo_url("/static/logo.png") is False
        assert svc._is_public_logo_url(None) is False

    def test_url_origin_strips_path(self):
        svc = _svc()
        assert svc._url_origin("https://x.test/a/b?q=1") == "https://x.test"
        assert svc._url_origin("not-a-url") is None

    def test_get_embedded_logo_html_falls_back_to_text_badge_when_no_logo(self):
        svc = _svc()
        with patch.object(svc, "_get_email_logo_url", return_value=None):
            html = svc._get_embedded_logo_html("Aryx", "http://localhost:3000")
        assert "Aryx" in html
        assert "<img" not in html

    def test_normalize_name(self):
        svc = _svc()
        assert svc._normalize_name("john_smith") == "John Smith"
        assert svc._normalize_name("") == ""
        assert svc._normalize_name(None) == ""

    def test_resolve_platform_name_prefers_explicit_then_company_then_default(self):
        svc = _svc()
        assert svc._resolve_platform_name({"platform_name": "Zaptag"}) == "Zaptag"
        assert svc._resolve_platform_name({"company_name": "Acme"}) == "Acme"
        assert svc._resolve_platform_name({}) == svc.default_platform_name
