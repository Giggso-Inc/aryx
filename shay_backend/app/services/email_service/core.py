"""
Core SMTP mechanics for EmailService: configuration, template loading, and
the single method that actually talks to an SMTP server.

Every other mixin in this package calls into `_send_email` / `_load_template`
defined here — this is the one seam every notification type depends on.
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart

from app.core.config import settings

logger = logging.getLogger(__name__)


class CoreMixin:
    """SMTP configuration, template file loading, and email dispatch."""

    def __init__(self):
        """Initialize email service with configuration"""
        # Get SMTP configuration from config.py
        self.host = settings.SMTP_HOST
        self.port = settings.SMTP_PORT
        self.username = settings.SMTP_USER
        self.password = settings.SMTP_PASS
        self.from_email = settings.SMTP_FROM
        self.use_tls = settings.SMTP_SECURE

        # Get default platform name from config
        self.default_platform_name = settings.PLATFORM_NAME

        logger.info(
            "EmailService initialised — host=%s port=%s from=%s tls=%s auth=%s",
            self.host, self.port, self.from_email, self.use_tls,
            bool(self.username),
        )

        # Get template directory path
        self.template_dir = os.path.join(
            os.path.dirname(__file__),
            '..', '..', '..', 'templates', 'email'
        )

    def _load_template(self, template_name: str) -> str:
        """
        Load HTML template from file

        Args:
            template_name: Name of the template file (e.g., 'password_reset.html')

        Returns:
            str: Template content as string

        Raises:
            FileNotFoundError: If template file doesn't exist
        """
        template_path = os.path.join(self.template_dir, template_name)

        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            print(f"⚠️ Template file not found: {template_path}")
            raise FileNotFoundError(f"Template file not found: {template_name}")
        except Exception as e:
            print(f"❌ Error loading template {template_name}: {e}")
            raise

    def _send_email(self, msg: MIMEMultipart) -> bool:
        """Send email via SMTP"""
        recipient = msg['To']
        try:
            logger.debug("SMTP connect — host=%s port=%s", self.host, self.port)
            server = smtplib.SMTP(self.host, self.port)

            if self.use_tls or self.port == 587:
                server.starttls()
                logger.debug("STARTTLS initiated")

            if self.username and self.password:
                try:
                    server.login(self.username, self.password)
                    logger.debug("SMTP login OK — user=%s", self.username)
                except smtplib.SMTPAuthenticationError as auth_error:
                    logger.error(
                        "SMTP authentication failed — user=%s error=%s",
                        self.username, auth_error, exc_info=True,
                    )
                    server.quit()
                    return False
                except smtplib.SMTPException as smtp_error:
                    if "AUTH extension not supported" in str(smtp_error):
                        logger.warning("SMTP server does not support AUTH, skipping login")
                    else:
                        logger.error("SMTP login error: %s", smtp_error, exc_info=True)
                        server.quit()
                        return False
            else:
                logger.warning("No SMTP credentials configured — sending unauthenticated")

            server.sendmail(self.from_email, recipient, msg.as_string())
            server.quit()
            logger.info("Email sent OK — to=%s from=%s", recipient, self.from_email)
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error("SMTP auth failed — to=%s: %s", recipient, e, exc_info=True)
            return False
        except smtplib.SMTPConnectError as e:
            logger.error(
                "SMTP connect error — host=%s port=%s to=%s: %s",
                self.host, self.port, recipient, e, exc_info=True,
            )
            return False
        except smtplib.SMTPRecipientsRefused as e:
            logger.error("SMTP recipient refused — to=%s: %s", recipient, e, exc_info=True)
            return False
        except smtplib.SMTPSenderRefused as e:
            logger.error(
                "SMTP sender refused — from=%s to=%s: %s",
                self.from_email, recipient, e, exc_info=True,
            )
            return False
        except smtplib.SMTPDataError as e:
            logger.error("SMTP data error — to=%s: %s", recipient, e, exc_info=True)
            return False
        except Exception as e:
            logger.error(
                "Unexpected error sending email — to=%s: %s",
                recipient, e, exc_info=True,
            )
            return False
