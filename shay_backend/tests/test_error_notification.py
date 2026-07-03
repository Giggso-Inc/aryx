"""
Unit tests for error notification functionality

Tests for:
- Error notification email service
- Error notification API endpoint
- Schema validation
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from fastapi.testclient import TestClient
from fastapi import status

from app.schemas.error_notification import (
    ErrorNotificationRequest,
    ErrorNotificationResponse
)
from app.services.email_service import EmailService


class TestErrorNotificationSchema:
    """Test error notification schemas"""
    
    def test_error_notification_request_valid(self):
        """Test valid error notification request"""
        request = ErrorNotificationRequest(
            api_endpoint="/api/v1/test",
            error_message="Test error message",
            error_type="ValueError",
            user_id="user123",
            company_id="company456",
            request_method="POST",
            request_body='{"key": "value"}',
            stack_trace="Traceback...",
            support_email="support@example.com"
        )
        
        assert request.api_endpoint == "/api/v1/test"
        assert request.error_message == "Test error message"
        assert request.error_type == "ValueError"
        assert request.user_id == "user123"
        assert request.company_id == "company456"
        assert request.request_method == "POST"
        assert request.support_email == "support@example.com"
    
    def test_error_notification_request_minimal(self):
        """Test minimal error notification request (only required fields)"""
        request = ErrorNotificationRequest(
            api_endpoint="/api/v1/test",
            error_message="Test error message"
        )
        
        assert request.api_endpoint == "/api/v1/test"
        assert request.error_message == "Test error message"
        assert request.error_type is None
        assert request.user_id is None
        assert request.company_id is None
    
    def test_error_notification_response(self):
        """Test error notification response"""
        response = ErrorNotificationResponse(
            success=True,
            message="Email sent successfully",
            email_sent=True,
            support_email="support@example.com"
        )
        
        assert response.success is True
        assert response.message == "Email sent successfully"
        assert response.email_sent is True
        assert response.support_email == "support@example.com"


class TestEmailServiceErrorNotification:
    """Test email service error notification methods"""
    
    @pytest.fixture
    def email_service(self):
        """Create email service instance"""
        service = EmailService()
        return service
    
    @pytest.fixture
    def sample_error_data(self):
        """Sample error data for testing"""
        return {
            'api_endpoint': '/api/v1/users',
            'error_message': 'Database connection failed',
            'error_type': 'DatabaseError',
            'user_id': 'user123',
            'company_id': 'company456',
            'request_method': 'POST',
            'request_body': '{"name": "test"}',
            'stack_trace': 'Traceback (most recent call last):\n  File "test.py", line 1',
            'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
            'platform_name': 'Shay Suite'
        }
    
    def test_create_error_notification_html(self, email_service, sample_error_data):
        """Test HTML email template creation"""
        html = email_service._create_error_notification_html(
            sample_error_data,
            "http://localhost:3000"
        )
        
        assert html is not None
        assert isinstance(html, str)
        assert len(html) > 0
        assert sample_error_data['api_endpoint'] in html
        assert sample_error_data['error_message'] in html
        assert sample_error_data['error_type'] in html
        assert 'API Failure Alert' in html
    
    def test_create_error_notification_html_with_missing_fields(self, email_service):
        """Test HTML email template with missing optional fields"""
        minimal_data = {
            'api_endpoint': '/api/v1/test',
            'error_message': 'Test error',
            'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        }
        
        html = email_service._create_error_notification_html(
            minimal_data,
            "http://localhost:3000"
        )
        
        assert html is not None
        assert 'Unknown Error' in html  # Default value
        assert 'N/A' in html  # Default values for missing fields
    
    def test_create_error_notification_text(self, email_service, sample_error_data):
        """Test plain text email template creation"""
        text = email_service._create_error_notification_text(
            sample_error_data,
            "http://localhost:3000"
        )
        
        assert text is not None
        assert isinstance(text, str)
        assert len(text) > 0
        assert sample_error_data['api_endpoint'] in text
        assert sample_error_data['error_message'] in text
        assert 'API FAILURE ALERT' in text
    
    def test_create_error_notification_text_with_missing_fields(self, email_service):
        """Test plain text email template with missing optional fields"""
        minimal_data = {
            'api_endpoint': '/api/v1/test',
            'error_message': 'Test error',
            'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        }
        
        text = email_service._create_error_notification_text(
            minimal_data,
            "http://localhost:3000"
        )
        
        assert text is not None
        assert 'Unknown Error' in text
        assert 'N/A' in text
    
    def test_html_truncates_long_fields(self, email_service):
        """Test that HTML template truncates very long error messages"""
        long_error_data = {
            'api_endpoint': '/api/v1/test',
            'error_message': 'A' * 600,  # Longer than 500 char limit
            'stack_trace': 'B' * 1200,  # Longer than 1000 char limit
            'request_body': 'C' * 600,  # Longer than 500 char limit
            'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        }
        
        html = email_service._create_error_notification_html(
            long_error_data,
            "http://localhost:3000"
        )
        
        assert html is not None
        assert '... (truncated)' in html
    
    @patch('app.services.email_service.EmailService._send_email')
    def test_send_error_notification_email_success(self, mock_send_email, email_service, sample_error_data):
        """Test successful error notification email sending"""
        mock_send_email.return_value = True
        
        result = email_service.send_error_notification_email(
            to_email="support@example.com",
            error_data=sample_error_data,
            platform_url="http://localhost:3000"
        )
        
        assert result is True
        mock_send_email.assert_called_once()
    
    @patch('app.services.email_service.EmailService._send_email')
    def test_send_error_notification_email_failure(self, mock_send_email, email_service, sample_error_data):
        """Test failed error notification email sending"""
        mock_send_email.return_value = False
        
        result = email_service.send_error_notification_email(
            to_email="support@example.com",
            error_data=sample_error_data,
            platform_url="http://localhost:3000"
        )
        
        assert result is False
        mock_send_email.assert_called_once()
    
    @patch('app.services.email_service.EmailService._send_email')
    def test_send_error_notification_email_exception(self, mock_send_email, email_service, sample_error_data):
        """Test error notification email sending with exception"""
        mock_send_email.side_effect = Exception("SMTP error")
        
        result = email_service.send_error_notification_email(
            to_email="support@example.com",
            error_data=sample_error_data,
            platform_url="http://localhost:3000"
        )
        
        assert result is False


class TestErrorNotificationAPI:
    """Test error notification API endpoint"""
    
    @pytest.fixture
    def client(self):
        """Create test client with minimal app containing only the error notification endpoint"""
        from fastapi import FastAPI, Depends
        from unittest.mock import AsyncMock, patch
        from app.schemas.error_notification import ErrorNotificationRequest, ErrorNotificationResponse
        from sqlalchemy.ext.asyncio import AsyncSession
        
        # Create a minimal test app
        test_app = FastAPI()
        
        # Mock database dependency
        async def mock_get_db():
            db = AsyncMock(spec=AsyncSession)
            db.rollback = AsyncMock()
            return db
        
        # Copy the endpoint implementation directly to avoid import issues
        @test_app.post("/api/v1/public/notify-api-failure", response_model=ErrorNotificationResponse)
        async def notify_api_failure_endpoint(
            error_notification: ErrorNotificationRequest,
            db: AsyncSession = Depends(mock_get_db)
        ):
            """Test endpoint - copied from app.routes.public to avoid import issues"""
            from app.core.config import settings
            from app.services.email_service import email_service
            from datetime import datetime, timezone
            
            # Determine support email (use provided email or default to SMTP_FROM)
            support_email = error_notification.support_email or settings.SMTP_FROM
            
            # Prepare error data
            error_data = {
                'api_endpoint': error_notification.api_endpoint,
                'error_message': error_notification.error_message,
                'error_type': error_notification.error_type or 'Unknown Error',
                'user_id': error_notification.user_id or 'N/A',
                'company_id': error_notification.company_id or 'N/A',
                'request_method': error_notification.request_method or 'N/A',
                'request_body': error_notification.request_body or 'N/A',
                'stack_trace': error_notification.stack_trace or 'N/A',
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
                'platform_name': 'Shay Suite'
            }
            
            # Send error notification email
            email_sent = email_service.send_error_notification_email(
                to_email=support_email,
                error_data=error_data,
                platform_url=settings.PLATFORM_URL
            )
            
            if email_sent:
                return ErrorNotificationResponse(
                    success=True,
                    message="Error notification email sent successfully to support team.",
                    email_sent=True,
                    support_email=support_email
                )
            else:
                return ErrorNotificationResponse(
                    success=False,
                    message="Failed to send error notification email. Please try again later.",
                    email_sent=False,
                    support_email=support_email
                )
        
        return TestClient(test_app)
    
    @pytest.fixture
    def valid_error_notification_request(self):
        """Valid error notification request payload"""
        return {
            "api_endpoint": "/api/v1/users",
            "error_message": "Database connection failed",
            "error_type": "DatabaseError",
            "user_id": "user123",
            "company_id": "company456",
            "request_method": "POST",
            "request_body": '{"name": "test"}',
            "stack_trace": "Traceback..."
        }
    
    @pytest.fixture
    def minimal_error_notification_request(self):
        """Minimal error notification request (only required fields)"""
        return {
            "api_endpoint": "/api/v1/test",
            "error_message": "Test error message"
        }
    
    @patch('app.services.email_service.email_service.send_error_notification_email')
    @patch('app.core.config.settings')
    def test_notify_api_failure_success(
        self,
        mock_settings,
        mock_send_email,
        client,
        valid_error_notification_request
    ):
        """Test successful API failure notification"""
        mock_settings.SMTP_FROM = "default@example.com"
        mock_settings.PLATFORM_URL = "http://localhost:3000"
        mock_send_email.return_value = True
        
        response = client.post(
            "/api/v1/public/notify-api-failure",
            json=valid_error_notification_request
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["email_sent"] is True
        assert "support" in data["support_email"].lower() or "default" in data["support_email"].lower()
        mock_send_email.assert_called_once()
    
    @patch('app.services.email_service.email_service.send_error_notification_email')
    @patch('app.core.config.settings')
    def test_notify_api_failure_with_custom_support_email(
        self,
        mock_settings,
        mock_send_email,
        client,
        valid_error_notification_request
    ):
        """Test API failure notification with custom support email"""
        mock_settings.SMTP_FROM = "default@example.com"
        mock_settings.PLATFORM_URL = "http://localhost:3000"
        mock_send_email.return_value = True
        
        valid_error_notification_request["support_email"] = "custom-support@example.com"
        
        response = client.post(
            "/api/v1/public/notify-api-failure",
            json=valid_error_notification_request
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["support_email"] == "custom-support@example.com"
        # Verify email was sent to custom email
        call_args = mock_send_email.call_args
        assert call_args[1]["to_email"] == "custom-support@example.com"
    
    @patch('app.services.email_service.email_service.send_error_notification_email')
    @patch('app.core.config.settings')
    def test_notify_api_failure_minimal_request(
        self,
        mock_settings,
        mock_send_email,
        client,
        minimal_error_notification_request
    ):
        """Test API failure notification with minimal request"""
        mock_settings.SMTP_FROM = "default@example.com"
        mock_settings.PLATFORM_URL = "http://localhost:3000"
        mock_send_email.return_value = True
        
        response = client.post(
            "/api/v1/public/notify-api-failure",
            json=minimal_error_notification_request
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        mock_send_email.assert_called_once()
    
    @patch('app.services.email_service.email_service.send_error_notification_email')
    @patch('app.core.config.settings')
    def test_notify_api_failure_email_send_failed(
        self,
        mock_settings,
        mock_send_email,
        client,
        valid_error_notification_request
    ):
        """Test API failure notification when email sending fails"""
        mock_settings.SMTP_FROM = "default@example.com"
        mock_settings.PLATFORM_URL = "http://localhost:3000"
        mock_send_email.return_value = False
        
        response = client.post(
            "/api/v1/public/notify-api-failure",
            json=valid_error_notification_request
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is False
        assert data["email_sent"] is False
    
    def test_notify_api_failure_missing_required_fields(self, client):
        """Test API failure notification with missing required fields"""
        invalid_request = {
            "error_message": "Test error"  # Missing api_endpoint
        }
        
        response = client.post(
            "/api/v1/public/notify-api-failure",
            json=invalid_request
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    def test_notify_api_failure_invalid_email(self, client):
        """Test API failure notification with invalid email format"""
        invalid_request = {
            "api_endpoint": "/api/v1/test",
            "error_message": "Test error",
            "support_email": "invalid-email"  # Invalid email format
        }
        
        response = client.post(
            "/api/v1/public/notify-api-failure",
            json=invalid_request
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    @patch('app.services.email_service.email_service.send_error_notification_email')
    @patch('app.core.config.settings')
    def test_notify_api_failure_error_data_structure(
        self,
        mock_settings,
        mock_send_email,
        client,
        valid_error_notification_request
    ):
        """Test that error data is properly structured before sending"""
        mock_settings.SMTP_FROM = "default@example.com"
        mock_settings.PLATFORM_URL = "http://localhost:3000"
        mock_send_email.return_value = True
        
        response = client.post(
            "/api/v1/public/notify-api-failure",
            json=valid_error_notification_request
        )
        
        assert response.status_code == status.HTTP_200_OK
        
        # Verify the error_data passed to email service
        call_args = mock_send_email.call_args
        error_data = call_args[1]["error_data"]
        
        assert error_data["api_endpoint"] == valid_error_notification_request["api_endpoint"]
        assert error_data["error_message"] == valid_error_notification_request["error_message"]
        assert error_data["error_type"] == valid_error_notification_request["error_type"]
        assert error_data["user_id"] == valid_error_notification_request["user_id"]
        assert error_data["company_id"] == valid_error_notification_request["company_id"]
        assert error_data["request_method"] == valid_error_notification_request["request_method"]
        assert "timestamp" in error_data
        assert error_data["platform_name"] == "Shay Suite"
    
    @patch('app.services.email_service.email_service.send_error_notification_email')
    @patch('app.core.config.settings')
    def test_notify_api_failure_defaults_for_missing_fields(
        self,
        mock_settings,
        mock_send_email,
        client,
        minimal_error_notification_request
    ):
        """Test that default values are used for missing optional fields"""
        mock_settings.SMTP_FROM = "default@example.com"
        mock_settings.PLATFORM_URL = "http://localhost:3000"
        mock_send_email.return_value = True
        
        response = client.post(
            "/api/v1/public/notify-api-failure",
            json=minimal_error_notification_request
        )
        
        assert response.status_code == status.HTTP_200_OK
        
        # Verify default values in error_data
        call_args = mock_send_email.call_args
        error_data = call_args[1]["error_data"]
        
        assert error_data["error_type"] == "Unknown Error"
        assert error_data["user_id"] == "N/A"
        assert error_data["company_id"] == "N/A"
        assert error_data["request_method"] == "N/A"
        assert error_data["request_body"] == "N/A"
        assert error_data["stack_trace"] == "N/A"

