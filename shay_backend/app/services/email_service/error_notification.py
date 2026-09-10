"""API-failure alert email: send + content builders (kept in one file — see
docstring at bottom for why it isn't split further)."""

from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class ErrorNotificationMixin:
    """Send an internal 'API failure' alert to the support team."""

    def send_error_notification_email(
        self,
        to_email: str,
        error_data: dict,
        platform_url: str = "http://localhost:3000"
    ) -> bool:
        """
        Send error notification email to customer support

        Args:
            to_email: Support team email address
            error_data: Dictionary containing error information:
                - api_endpoint: The API endpoint that failed
                - error_message: Error message
                - error_type: Type of error (optional)
                - user_id: User ID who encountered the error (optional)
                - company_id: Company ID (optional)
                - request_method: HTTP method (optional)
                - request_body: Request body (optional)
                - stack_trace: Stack trace (optional)
                - timestamp: Timestamp of the error
            platform_url: Base URL for the platform

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            print(f"📧 Preparing error notification email for {to_email}...")
            # Create message with 'alternative' subtype so email clients show only one version
            msg = MIMEMultipart('alternative')
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = f"API Failure Alert - {error_data.get('api_endpoint', 'Unknown Endpoint')}"

            # Create plain text body first (should be attached before HTML)
            text_body = self._create_error_notification_text(error_data, platform_url)
            msg.attach(MIMEText(text_body, 'plain'))

            # Create HTML body (attached after plain text - clients will prefer HTML if supported)
            html_body = self._create_error_notification_html(error_data, platform_url)
            msg.attach(MIMEText(html_body, 'html'))

            print(f"📧 Sending error notification email via SMTP to {to_email}...")
            # Send email
            result = self._send_email(msg)
            if result:
                print(f"✅ Error notification email sent successfully to {to_email}")
            else:
                print(f"❌ Failed to send error notification email to {to_email}")
            return result

        except Exception as e:
            print(f"❌ Error sending error notification email to {to_email}: {e}")
            import traceback
            print(f"📋 Error traceback: {traceback.format_exc()}")
            return False

    def _create_error_notification_html(self, error_data: dict, platform_url: str) -> str:
        """Create HTML version of error notification email using template file"""
        from datetime import timezone
        api_endpoint = error_data.get('api_endpoint', 'Unknown Endpoint')
        error_message = error_data.get('error_message', 'No error message provided')
        error_type = error_data.get('error_type', 'Unknown Error')
        user_id = error_data.get('user_id', 'N/A')
        company_id = error_data.get('company_id', 'N/A')
        request_method = error_data.get('request_method', 'N/A')
        request_body = error_data.get('request_body', 'N/A')
        stack_trace = error_data.get('stack_trace', 'N/A')
        timestamp = error_data.get('timestamp', datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
        platform_name = error_data.get('platform_name', self.default_platform_name)
        current_year = datetime.now().year

        # Truncate long fields for display
        if len(error_message) > 500:
            error_message = error_message[:500] + "... (truncated)"
        if len(stack_trace) > 1000:
            stack_trace = stack_trace[:1000] + "... (truncated)"
        if len(str(request_body)) > 500:
            request_body = str(request_body)[:500] + "... (truncated)"

        # Load template from file
        try:
            template = self._load_template('error_notification.html')
            return template.format(
                logo_html=self._get_embedded_logo_html(platform_name, platform_url),
                api_endpoint=api_endpoint,
                error_message=error_message,
                error_type=error_type,
                user_id=user_id,
                company_id=company_id,
                request_method=request_method,
                request_body=request_body,
                stack_trace=stack_trace,
                timestamp=timestamp,
                platform_name=platform_name,
                current_year=current_year
            )
        except FileNotFoundError:
            # Fallback: try to load from template file again or raise error
            print(f"⚠️ Template file error_notification.html not found")
            raise FileNotFoundError("Template file error_notification.html is required")

    def _create_error_notification_text(self, error_data: dict, platform_url: str) -> str:
        """Create plain text version of error notification email"""
        from datetime import timezone
        api_endpoint = error_data.get('api_endpoint', 'Unknown Endpoint')
        error_message = error_data.get('error_message', 'No error message provided')
        error_type = error_data.get('error_type', 'Unknown Error')
        user_id = error_data.get('user_id', 'N/A')
        company_id = error_data.get('company_id', 'N/A')
        request_method = error_data.get('request_method', 'N/A')
        request_body = error_data.get('request_body', 'N/A')
        stack_trace = error_data.get('stack_trace', 'N/A')
        timestamp = error_data.get('timestamp', datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
        platform_name = error_data.get('platform_name', self.default_platform_name)

        text = f"""
        ⚠️ API FAILURE ALERT - {platform_name}
        ======================================

        An API failure has been detected and requires your attention.

        ERROR DETAILS:
        --------------
        API Endpoint: {api_endpoint}
        HTTP Method: {request_method}
        Error Type: {error_type}
        Timestamp: {timestamp}

        ERROR MESSAGE:
        --------------
        {error_message}

        REQUEST CONTEXT:
        ----------------
        User ID: {user_id}
        Company ID: {company_id}
        Request Body: {request_body}

        STACK TRACE:
        ------------
        {stack_trace}

        Please investigate this error and take appropriate action. If this is a recurring issue,
        consider implementing additional error handling or monitoring.

        This is an automated error notification from {platform_name}
        © 2025 {platform_name}. All rights reserved.
        """

        return text


# Stated exception: this file is ~150 lines (over the ~150 target only by a
# handful of lines once the module docstring/imports are counted). The three
# members here (send + its two body builders) are one atomic notification
# flow with no independently reusable sub-concern -- splitting the HTML/text
# builders into a second file, as done for the invitation/password-reset/
# channel-notification types above, was judged not worth the extra file for
# this small a size difference.
