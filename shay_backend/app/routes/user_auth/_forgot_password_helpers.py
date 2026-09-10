"""
Private helpers for forgot_password.py's forgot_password endpoint.

Split out of the original password_reset.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up) so
forgot_password.py itself stays under the 150-line limit.

The three names tests/test_user_auth_reset.py patches
(`email_verification_service`, `link_shortener_service`,
`_send_default_password_reset_email`) are all used inside
`_generate_and_send_reset_email` below, so those tests now target
`app.routes.user_auth._forgot_password_helpers.<name>` instead of the old
`app.routes.user_auth.password_reset.<name>`.
"""

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from fastapi import HTTPException

from app.core.config import settings
from app.models.email_verification_token import EmailVerificationToken
from app.services.email_service import EmailService
from app.services.email_verification_service import email_verification_service
from app.services.link_shortener_service import link_shortener_service
from app.services.template_service import template_service

from app.routes.user_auth._shared import _send_default_password_reset_email


def _product_name_from_base_url(base_url: str) -> str:
    """Map a frontend base URL to the product name used in the reset email."""
    base_url = base_url.lower().strip()
    if "dev-zaptag.shay-ai.com" in base_url:
        return "ZapTag"
    elif "zaptag.accsell.ai" in base_url:
        return "ZapTag"  # ZapTag production
    elif "dev-loger.shay-ai.com" in base_url:
        return "Log Analyser"
    elif "dev-fourd.shay-ai.com" in base_url:
        return "Email Support App"
    elif "dev-accell.shay-ai.com" in base_url:
        return "Accsell"
    elif "app.accsell.ai" in base_url:
        return "Accsell"  # Production Accsell
    else:
        return "Shay Suite"  # Default fallback


async def _generate_and_send_reset_email(user, base_url, product_name, template_id, db) -> tuple:
    """
    Issue a password-reset token, shorten its link, and email it to the user.

    Returns (email_sent, short_reset_url_or_None).
    """
    email_sent = False
    short_reset_url = None
    try:
        await email_verification_service.invalidate_existing_tokens(
            user.email_id,
            "password_reset",
            db,
        )
        reset_token = EmailVerificationToken.create_token(
            email=user.email_id,
            company_id=user.company_id,
            user_id=user.id,
            token_type="password_reset",
            expires_in_hours=1,
        )
        db.add(reset_token)
        await db.flush()

        # Persist the reset token before any optional email-link shortening work.
        # The shortener uses the same DB session and can fail independently (for
        # example, when its table is unavailable), but the reset token itself must
        # still survive so the emailed link can be redeemed.
        await db.commit()

        reset_url = f"{base_url.rstrip('/')}/reset-password?token={reset_token.token}"
        short_reset_url = await link_shortener_service.shorten(reset_url, db=db)

        template_variables = {
            'user_name': user.name or 'User',
            'company_name': product_name,
            'reset_link': short_reset_url,
            'expiry_hours': 1,
            'email': user.email_id,
            'token': reset_token.token
        }

        if template_id:
            try:
                template_data = await template_service.get_template_content(template_id, db)
                processed_html = template_service.process_template_content(
                    template_data['content'], template_variables
                )
                msg = _build_templated_reset_email_message(
                    product_name, user.email_id, processed_html, template_variables, short_reset_url
                )
                email_service = EmailService()
                email_sent = email_service._send_email(msg)
            except HTTPException as e:
                print(f"❌ Template not found or error: {e.detail}")
                email_sent = await _send_default_password_reset_email(user, short_reset_url, product_name)
            except Exception as e:
                print(f"❌ Error processing template: {e}")
                email_sent = await _send_default_password_reset_email(user, short_reset_url, product_name)
        else:
            email_sent = await _send_default_password_reset_email(user, short_reset_url, product_name)

    except Exception as e:
        print(f"❌ Error sending forgot password email: {e}")
        email_sent = False

    return email_sent, short_reset_url


def _build_templated_reset_email_message(product_name, to_email, processed_html, template_variables, short_reset_url) -> MIMEMultipart:
    """Build the MIME message for a template-based password reset email."""
    msg = MIMEMultipart('related')
    msg['Subject'] = f"Password Reset - {product_name} Account"
    msg['From'] = settings.SMTP_FROM
    msg['To'] = to_email

    html_wrapper = MIMEMultipart('alternative')

    html_part = MIMEText(processed_html, 'html', 'utf-8')
    html_part.add_header('Content-Type', 'text/html; charset=utf-8')
    html_wrapper.attach(html_part)

    text_content = f"""Password Reset Request - {product_name} Account

Hello {template_variables['user_name']},

We received a request to reset your password for your {product_name} account.

Reset Link: {short_reset_url}

This link will expire in 1 hour.

© 2025 {product_name}. All rights reserved."""

    text_part = MIMEText(text_content, 'plain', 'utf-8')
    html_wrapper.attach(text_part)

    msg.attach(html_wrapper)
    return msg
