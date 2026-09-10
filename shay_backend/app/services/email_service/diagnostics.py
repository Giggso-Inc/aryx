"""
Manual SMTP diagnostic helpers (not used by any notification-sending flow) —
kept separate from core.py so the SMTP config test tools don't dilute the
actual send-path file.
"""

import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict


class DiagnosticsMixin:
    """Ad-hoc connection/test-send helpers used by ops/debug tooling."""

    def test_connection(self) -> bool:
        """Test SMTP connection"""
        try:
            server = smtplib.SMTP(self.host, self.port)

            # For Gmail and most modern SMTP servers, we need to start TLS first
            if self.use_tls or self.port == 587:  # Use TLS setting or standard TLS port
                server.starttls()
                print("✅ STARTTLS initiated successfully")

            # Try to login if credentials are provided
            if self.username and self.password:
                try:
                    server.login(self.username, self.password)
                    print("✅ SMTP authentication successful")
                except smtplib.SMTPAuthenticationError as auth_error:
                    print(f"❌ SMTP authentication failed: {auth_error}")
                    server.quit()
                    return False
                except smtplib.SMTPException as smtp_error:
                    if "AUTH extension not supported" in str(smtp_error):
                        print("⚠️ SMTP server doesn't support authentication, continuing without login")
                    else:
                        print(f"❌ SMTP error: {smtp_error}")
                        server.quit()
                        return False
            else:
                print("⚠️ No SMTP credentials provided, testing connection only")

            server.quit()
            print("✅ SMTP connection test successful")
            return True

        except Exception as e:
            print(f"❌ SMTP connection test failed: {e}")
            return False

    def test_email_sending(self, test_email: str = "test@example.com") -> Dict[str, Any]:
        """Test email sending with current configuration"""
        try:
            # Create a simple test message
            msg = MIMEMultipart()
            msg['From'] = self.from_email
            msg['To'] = test_email
            msg['Subject'] = f'Test Email from {self.default_platform_name}'

            body = f"""
            This is a test email from {self.default_platform_name}.

            Configuration:
            - Host: {self.host}
            - Port: {self.port}
            - Username: {self.username}
            - From: {self.from_email}
            - TLS: {self.use_tls}

            Sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """

            msg.attach(MIMEText(body, 'plain'))

            # Try to send the test email
            success = self._send_email(msg)

            if success:
                return {
                    'success': True,
                    'message': f'Test email sent successfully to {test_email}',
                    'configuration': {
                        'host': self.host,
                        'port': self.port,
                        'username': self.username,
                        'from_email': self.from_email,
                        'use_tls': self.use_tls
                    }
                }
            else:
                return {
                    'success': False,
                    'message': f'Failed to send test email to {test_email}',
                    'configuration': {
                        'host': self.host,
                        'port': self.port,
                        'username': self.username,
                        'from_email': self.from_email,
                        'use_tls': self.use_tls
                    }
                }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': f'Test email failed: {str(e)}',
                'configuration': {
                    'host': self.host,
                    'port': self.port,
                    'username': self.username,
                    'from_email': self.from_email,
                    'use_tls': self.use_tls
                }
            }
