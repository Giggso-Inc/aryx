"""
Test cases for ML service embedd_type functionality
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.ml_service import get_embedd_type_from_file_type, MLService


class TestGetEmbeddTypeFromFileType:
    """Test cases for get_embedd_type_from_file_type function"""
    
    def test_textual_mime_types(self):
        """Test that textual MIME types return 'textual'"""
        textual_types = [
            'text/plain',
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.ms-powerpoint',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'application/rtf',
            'text/rtf'
        ]
        
        for file_type in textual_types:
            assert get_embedd_type_from_file_type(file_type) == "textual"
    
    def test_tabular_mime_types(self):
        """Test that tabular MIME types return 'tabular'"""
        tabular_types = [
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'text/csv',
            'application/csv',
            'application/json',
            'text/json'
        ]
        
        for file_type in tabular_types:
            assert get_embedd_type_from_file_type(file_type) == "tabular"
    
    def test_textual_file_extensions(self):
        """Test that textual file extensions return 'textual'"""
        textual_extensions = [
            'txt', 'pdf', 'doc', 'docx', 'ppt', 'pptx', 
            'rtf', 'html', 'htm', 'css', 'js'
        ]
        
        for extension in textual_extensions:
            assert get_embedd_type_from_file_type(extension) == "textual"
    
    def test_tabular_file_extensions(self):
        """Test that tabular file extensions return 'tabular'"""
        tabular_extensions = ['xls', 'xlsx', 'csv', 'json']
        
        for extension in tabular_extensions:
            assert get_embedd_type_from_file_type(extension) == "tabular"
    
    def test_edge_cases(self):
        """Test edge cases return 'textual' as default"""
        edge_cases = [
            None,
            "",
            "unknown_type",
            "image/jpeg",
            "video/mp4",
            "application/zip"
        ]
        
        for file_type in edge_cases:
            assert get_embedd_type_from_file_type(file_type) == "textual"
    
    def test_case_insensitive(self):
        """Test that function is case insensitive"""
        assert get_embedd_type_from_file_type("TEXT/PLAIN") == "textual"
        assert get_embedd_type_from_file_type("APPLICATION/PDF") == "textual"
        assert get_embedd_type_from_file_type("TXT") == "textual"
        assert get_embedd_type_from_file_type("XLSX") == "tabular"
        assert get_embedd_type_from_file_type("CSV") == "tabular"


class TestMLServiceEmbeddType:
    """Test cases for MLService with embedd_type functionality"""
    
    @pytest.fixture
    def ml_service(self):
        """Create MLService instance for testing"""
        return MLService()
    
    @pytest.mark.asyncio
    async def test_request_embedding_processing_with_textual_type(self, ml_service):
        """Test ML API request with textual embedd_type"""
        with patch('httpx.AsyncClient') as mock_client:
            # Mock successful response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "success"}
            mock_response.text = '{"status": "success"}'
            mock_response.headers = {}
            
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            
            result = await ml_service.request_embedding_processing(
                vault_unique_ids=["test_vault_id"],
                user_id="test_user_id",
                company_id="test_company_id",
                channel_id="test_channel_id",
                embedd_type="textual"
            )
            
            # Verify the request was made with correct payload
            mock_client.return_value.__aenter__.return_value.post.assert_called_once()
            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            
            # Check the JSON payload
            json_payload = call_args[1]['json']
            assert json_payload['embeddType'] == "textual"
            assert json_payload['channelId'] == "test_channel_id"
            assert json_payload['dataSourcesVaultTokens'] == ["test_vault_id"]
            assert json_payload['userId'] == "test_user_id"
            assert json_payload['companyId'] == "test_company_id"
            
            # Check the result
            assert result['success'] is True
    
    @pytest.mark.asyncio
    async def test_request_embedding_processing_with_tabular_type(self, ml_service):
        """Test ML API request with tabular embedd_type"""
        with patch('httpx.AsyncClient') as mock_client:
            # Mock successful response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "success"}
            mock_response.text = '{"status": "success"}'
            mock_response.headers = {}
            
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            
            result = await ml_service.request_embedding_processing(
                vault_unique_ids=["test_vault_id"],
                user_id="test_user_id",
                company_id="test_company_id",
                channel_id="test_channel_id",
                embedd_type="tabular"
            )
            
            # Verify the request was made with correct payload
            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            json_payload = call_args[1]['json']
            assert json_payload['embeddType'] == "tabular"
    
    @pytest.mark.asyncio
    async def test_request_embedding_processing_default_type(self, ml_service):
        """Test ML API request with default embedd_type (textual)"""
        with patch('httpx.AsyncClient') as mock_client:
            # Mock successful response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "success"}
            mock_response.text = '{"status": "success"}'
            mock_response.headers = {}
            
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            
            result = await ml_service.request_embedding_processing(
                vault_unique_ids=["test_vault_id"],
                user_id="test_user_id",
                company_id="test_company_id",
                channel_id="test_channel_id"
                # No embedd_type specified, should default to "textual"
            )
            
            # Verify the request was made with default payload
            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            json_payload = call_args[1]['json']
            assert json_payload['embeddType'] == "textual"
    
    @pytest.mark.asyncio
    async def test_request_embedding_processing_with_embedded_vault_ids(self, ml_service):
        """Test ML API request with embedded vault IDs"""
        with patch('httpx.AsyncClient') as mock_client:
            # Mock successful response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "success"}
            mock_response.text = '{"status": "success"}'
            mock_response.headers = {}
            
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            
            result = await ml_service.request_embedding_processing(
                vault_unique_ids=["test_vault_id"],
                user_id="test_user_id",
                company_id="test_company_id",
                channel_id="test_channel_id",
                embedded_vault_unique_ids=["embedded_vault_id"],
                embedd_type="textual"
            )
            
            # Verify the request was made with correct payload
            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            json_payload = call_args[1]['json']
            assert json_payload['embeddedDataSourceVaultTokens'] == ["embedded_vault_id"]
    
    @pytest.mark.asyncio
    async def test_request_embedding_processing_with_jwt_token(self, ml_service):
        """Test ML API request with JWT token authentication"""
        with patch('httpx.AsyncClient') as mock_client:
            # Mock successful response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "success"}
            mock_response.text = '{"status": "success"}'
            mock_response.headers = {}
            
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            
            result = await ml_service.request_embedding_processing(
                vault_unique_ids=["test_vault_id"],
                user_id="test_user_id",
                company_id="test_company_id",
                channel_id="test_channel_id",
                jwt_token="test_jwt_token",
                embedd_type="textual"
            )
            
            # Verify the request was made with correct headers
            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            headers = call_args[1]['headers']
            assert headers['Authorization'] == "Bearer test_jwt_token"
    
    @pytest.mark.asyncio
    async def test_request_embedding_processing_api_error(self, ml_service):
        """Test ML API request with API error response"""
        with patch('httpx.AsyncClient') as mock_client:
            # Mock error response
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.text = '{"error": "Bad request"}'
            mock_response.headers = {}
            
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            
            result = await ml_service.request_embedding_processing(
                vault_unique_ids=["test_vault_id"],
                user_id="test_user_id",
                company_id="test_company_id",
                channel_id="test_channel_id",
                embedd_type="textual"
            )
            
            # Check the result
            assert result['success'] is False
            assert "ML API error: 400" in result['message']
    
    @pytest.mark.asyncio
    async def test_request_embedding_processing_timeout(self, ml_service):
        """Test ML API request with timeout"""
        with patch('httpx.AsyncClient') as mock_client:
            # Mock timeout exception
            from httpx import TimeoutException
            mock_client.return_value.__aenter__.return_value.post.side_effect = TimeoutException("Request timed out")
            
            result = await ml_service.request_embedding_processing(
                vault_unique_ids=["test_vault_id"],
                user_id="test_user_id",
                company_id="test_company_id",
                channel_id="test_channel_id",
                embedd_type="textual"
            )
            
            # Check the result
            assert result['success'] is False
            assert "Timeout while calling ML API" in result['message']
    
    @pytest.mark.asyncio
    async def test_request_embedding_processing_connection_error(self, ml_service):
        """Test ML API request with connection error"""
        with patch('httpx.AsyncClient') as mock_client:
            # Mock connection error
            from httpx import RequestError
            mock_client.return_value.__aenter__.return_value.post.side_effect = RequestError("Connection failed")
            
            result = await ml_service.request_embedding_processing(
                vault_unique_ids=["test_vault_id"],
                user_id="test_user_id",
                company_id="test_company_id",
                channel_id="test_channel_id",
                embedd_type="textual"
            )
            
            # Check the result
            assert result['success'] is False
            assert "Failed to connect to ML API" in result['message']
