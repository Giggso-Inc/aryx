"""Branding and content tests for Aryx email templates and generators."""

from __future__ import annotations

from datetime import datetime
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.daily_summary_scheduler import DailySummaryScheduler
from app.services.email_service import EmailService


EXPECTED_GRADIENT = "linear-gradient(135deg, #0D1B5A 0%, #1E3A8A 60%, #2D7DFF 100%)"
FORBIDDEN_BRAND_STRINGS = (
    "Prism 7",
    "Prism7",
    "Welcome to Shay",
    "Shay Team",
    "Shay Suite",
    "AI-powered collaboration platform",
    "AI-Powered Collaboration Platform",
)


def assert_no_legacy_branding(content: str) -> None:
    """Ensure no old-brand copy survives in the rendered body."""
    for forbidden in FORBIDDEN_BRAND_STRINGS:
        assert forbidden not in content


def assert_aryx_html_branding(content: str) -> None:
    """Ensure rendered HTML uses the Aryx brand frame."""
    assert EXPECTED_GRADIENT in content
    assert "#2D7DFF" in content
    assert "#0D1B5A" in content
    assert "Aryx" in content
    assert_no_legacy_branding(content)


@pytest.fixture
def email_service() -> EmailService:
    """Create a fresh email service instance."""
    return EmailService()


def test_all_checked_in_email_templates_use_aryx_branding() -> None:
    """Every checked-in email template should use the Aryx frame and no legacy copy."""
    template_dir = Path(__file__).resolve().parents[1] / "templates" / "email"
    for template_path in template_dir.glob("*.html"):
        content = template_path.read_text(encoding="utf-8")
        assert EXPECTED_GRADIENT in content, template_path.name
        assert "#2D7DFF" in content, template_path.name
        assert_no_legacy_branding(content)


def test_invitation_rendering_is_aryx_branded(email_service: EmailService) -> None:
    invitation_data = {
        "company_name": "Acme Corp",
        "registration_link": "https://aryx.example.com/invite/abc",
        "registration_short_link": "https://aryx.example.com/i/abc",
        "email": "alex@example.com",
        "user_name": "Alex",
        "invited_by": "sara_admin",
        "support_email": "support@aryx.example.com",
        "platform_name": "Aryx",
    }

    html = email_service._create_invitation_html(invitation_data, "https://aryx.example.com")
    text = email_service._create_invitation_text(invitation_data, "https://aryx.example.com")

    assert_aryx_html_branding(html)
    assert 'width: 180px; padding: 24px 24px 24px 0;' in html
    assert 'padding: 24px 12px; text-align: center; vertical-align: middle;' in html
    assert "Acme Corp" in html
    assert "Accept Invitation" in html
    assert "searchable knowledge graph" in text
    assert "data:image" not in html
    assert len(html) < 20_000
    assert_no_legacy_branding(text)


def test_invitation_subject_is_fixed_to_aryx(email_service: EmailService, monkeypatch: pytest.MonkeyPatch) -> None:
    invitation_data = {
        "company_name": "Acme Corp",
        "registration_link": "https://aryx.example.com/invite/abc",
        "registration_short_link": "https://aryx.example.com/i/abc",
        "email": "alex@example.com",
        "user_name": "Alex",
        "invited_by": "sara_admin",
        "support_email": "support@aryx.example.com",
        "platform_name": "Acme Corp",
    }

    captured = {}

    def fake_send_email(msg):
        captured["subject"] = msg["Subject"]
        return True

    monkeypatch.setattr(email_service, "_send_email", fake_send_email)

    result = email_service.send_invitation_email(
        "alex@example.com",
        invitation_data,
        "https://aryx.example.com",
    )

    assert result is True
    assert captured["subject"] == "Invitation to join Aryx"


def test_template_invitation_subject_is_fixed_to_aryx(email_service: EmailService, monkeypatch: pytest.MonkeyPatch) -> None:
    invitation_data = {
        "company_name": "Acme Corp",
        "registration_link": "https://aryx.example.com/invite/abc",
        "registration_short_link": "https://aryx.example.com/i/abc",
        "email": "alex@example.com",
        "user_name": "Alex",
        "invited_by": "sara_admin",
        "support_email": "support@aryx.example.com",
        "platform_name": "Acme Corp",
    }

    captured = {}

    def fake_send_email(msg):
        captured["subject"] = msg["Subject"]
        return True

    monkeypatch.setattr(email_service, "_send_email", fake_send_email)

    result = asyncio.run(
        email_service.send_template_invitation_email(
            "alex@example.com",
            invitation_data,
            template_id=None,
            platform_url="https://aryx.example.com",
            db=None,
        )
    )

    assert result is True
    assert captured["subject"] == "Invitation to join Aryx"


def test_embedded_logo_falls_back_when_asset_is_large(email_service: EmailService) -> None:
    """Large inline logo assets should not be embedded into email bodies."""
    logo_html = email_service._get_embedded_logo_html("Aryx")

    assert "data:image" not in logo_html
    assert "Aryx" in logo_html


def test_verification_rendering_is_aryx_branded(email_service: EmailService) -> None:
    verification_data = {
        "company_name": "Acme Corp",
        "user_name": "Alex",
        "verification_link": "https://aryx.example.com/verify/token",
        "expires_in_hours": 24,
        "support_email": "support@aryx.example.com",
        "platform_name": "Aryx",
    }

    html = email_service._create_verification_html(verification_data, "https://aryx.example.com")
    text = email_service._create_verification_text(verification_data, "https://aryx.example.com")

    assert_aryx_html_branding(html)
    assert "Verify Email Address" in html
    assert "activate your Aryx workspace" in text
    assert_no_legacy_branding(text)


def test_password_reset_rendering_is_aryx_branded(email_service: EmailService) -> None:
    password_reset_data = {
        "email": "alex@example.com",
        "user_name": "Alex",
        "reset_url": "https://aryx.example.com/reset/token",
        "expires_at": "1 hour",
        "support_email": "support@aryx.example.com",
        "platform_name": "Aryx",
    }

    html = email_service._create_password_reset_html(password_reset_data, "https://aryx.example.com")
    text = email_service._create_password_reset_text(password_reset_data, "https://aryx.example.com")

    assert_aryx_html_branding(html)
    assert "Reset Password" in html
    assert "continue working in Aryx" in text
    assert_no_legacy_branding(text)


def test_welcome_rendering_is_aryx_branded(email_service: EmailService) -> None:
    welcome_data = {
        "companyName": "Acme Corp",
        "contactEmail": "ops@acme.example.com",
        "planName": "Growth",
        "monthlyPrice": 499,
        "appLink": "https://aryx.example.com/app",
        "platform_name": "Aryx",
    }

    html = email_service._create_welcome_email_template(welcome_data)
    text = email_service._create_text_welcome_email(welcome_data)

    assert_aryx_html_branding(html)
    assert "Launch Workspace" in html
    assert "workspace is ready" in text
    assert_no_legacy_branding(text)


def test_channel_member_rendering_is_aryx_branded(email_service: EmailService) -> None:
    notification_data = {
        "channel_id": "channel-123",
        "channel_name": "Entity Review",
        "user_name": "Alex",
        "user_email": "alex@example.com",
        "user_role": "member",
        "added_by": "Sara",
        "platform_name": "Aryx",
    }

    html = email_service._create_channel_member_notification_html(
        notification_data,
        "https://aryx.example.com",
        send_to_added_user=True,
    )
    text = email_service._create_channel_member_notification_text(
        notification_data,
        "https://aryx.example.com",
        send_to_added_user=True,
    )

    assert_aryx_html_branding(html)
    assert "View Channel" in html
    assert "You have been added to the channel" in text
    assert_no_legacy_branding(text)


def test_support_request_rendering_is_aryx_branded(email_service: EmailService) -> None:
    support_data = {
        "name": "Alex",
        "email": "alex@example.com",
        "description": "Need help mapping customer entities.",
        "subject": "Ontology mapping",
        "ticket_reference": "ARYX-101",
        "created_at": "2026-06-30 15:00:00 UTC",
        "company_id": "comp-1",
        "company_name": "Acme Corp",
        "user_id": "user-1",
        "platform_name": "Aryx",
    }

    html = email_service._create_support_request_html(support_data, "https://aryx.example.com")
    text = email_service._create_support_request_text(support_data, "https://aryx.example.com")

    assert_aryx_html_branding(html)
    assert "ARYX-101" in html
    assert "New Support Request - Aryx" in text
    assert_no_legacy_branding(text)


def test_support_confirmation_rendering_is_aryx_branded(email_service: EmailService) -> None:
    support_data = {
        "name": "Alex",
        "ticket_reference": "ARYX-102",
        "platform_name": "Aryx",
    }

    html = email_service._create_support_confirmation_html(support_data, "https://aryx.example.com")
    text = email_service._create_support_confirmation_text(support_data, "https://aryx.example.com")

    assert_aryx_html_branding(html)
    assert "ARYX-102" in html
    assert "Aryx Support" in text
    assert_no_legacy_branding(text)


def test_error_notification_rendering_is_aryx_branded(email_service: EmailService) -> None:
    error_data = {
        "api_endpoint": "/api/v1/graph/query",
        "error_message": "FalkorDB timeout",
        "error_type": "TimeoutError",
        "user_id": "user-1",
        "company_id": "comp-1",
        "request_method": "POST",
        "request_body": '{"query":"MATCH (n) RETURN n"}',
        "stack_trace": "Traceback: timeout",
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "platform_name": "Aryx",
    }

    html = email_service._create_error_notification_html(error_data, "https://aryx.example.com")
    text = email_service._create_error_notification_text(error_data, "https://aryx.example.com")

    assert_aryx_html_branding(html)
    assert "API failure alert" in html
    assert "API FAILURE ALERT - Aryx" in text
    assert_no_legacy_branding(text)


def test_daily_summary_rendering_is_aryx_branded() -> None:
    scheduler = DailySummaryScheduler()
    user = SimpleNamespace(name="Alex", email_id="alex@example.com")
    email_settings = SimpleNamespace(
        mention_enabled=1,
        post_enabled=0,
        reply_enabled=0,
        task_enabled=1,
        approval_pending_enabled=1,
        meeting_enabled=0,
        blocker_enabled=0,
        app_enabled=0,
        chat_enabled=0,
        friend_enabled=0,
    )
    notification_counts = {
        "mentions": 3,
        "tasks": 2,
        "approvals": 1,
    }
    top_channels = [
        {
            "channel_name": "Entity Review",
            "channel_url": "https://aryx.example.com/channels/entity-review",
            "notification_count": 4,
        }
    ]

    enabled_cards = scheduler.generate_enabled_cards(email_settings, notification_counts)
    html = scheduler.generate_email_content(
        user,
        email_settings,
        notification_counts,
        top_channels,
        enabled_cards,
    )

    assert_aryx_html_branding(html)
    assert "Top channels by activity" in html
    assert "Entity Review" in html
