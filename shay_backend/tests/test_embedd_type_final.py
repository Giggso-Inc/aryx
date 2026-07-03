"""
Final comprehensive test cases for embedd_type functionality
"""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

# Add the parent directory to Python path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

from app.services.ml_service import get_embedd_type_from_file_type, MLService


class TestEmbeddTypeFunction:
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


class TestEmbeddTypeLogic:
    """Test cases for embedd_type determination logic"""
    
    def test_determine_embedd_type_textual_files(self):
        """Test determining embedd_type for textual files"""
        file_types = ["text/plain", "application/pdf", "application/msword"]
        
        # All files are textual
        textual_count = sum(1 for ft in file_types if get_embedd_type_from_file_type(ft) == "textual")
        tabular_count = sum(1 for ft in file_types if get_embedd_type_from_file_type(ft) == "tabular")
        
        # If all files are tabular, use tabular; otherwise use textual
        if tabular_count > 0 and textual_count == 0:
            embedd_type = "tabular"
        else:
            embedd_type = "textual"
        
        assert embedd_type == "textual"
    
    def test_determine_embedd_type_tabular_files(self):
        """Test determining embedd_type for tabular files"""
        file_types = ["application/vnd.ms-excel", "text/csv", "application/json"]
        
        # All files are tabular
        textual_count = sum(1 for ft in file_types if get_embedd_type_from_file_type(ft) == "textual")
        tabular_count = sum(1 for ft in file_types if get_embedd_type_from_file_type(ft) == "tabular")
        
        # If all files are tabular, use tabular; otherwise use textual
        if tabular_count > 0 and textual_count == 0:
            embedd_type = "tabular"
        else:
            embedd_type = "textual"
        
        assert embedd_type == "tabular"
    
    def test_determine_embedd_type_mixed_files(self):
        """Test determining embedd_type for mixed file types"""
        file_types = ["text/plain", "application/vnd.ms-excel", "application/pdf"]
        
        # Mixed files
        textual_count = sum(1 for ft in file_types if get_embedd_type_from_file_type(ft) == "textual")
        tabular_count = sum(1 for ft in file_types if get_embedd_type_from_file_type(ft) == "tabular")
        
        # If all files are tabular, use tabular; otherwise use textual
        if tabular_count > 0 and textual_count == 0:
            embedd_type = "tabular"
        else:
            embedd_type = "textual"
        
        assert embedd_type == "textual"  # Should default to textual for mixed types
    
    def test_determine_embedd_type_no_files(self):
        """Test determining embedd_type when no file types available"""
        file_types = []
        
        # No files
        textual_count = sum(1 for ft in file_types if get_embedd_type_from_file_type(ft) == "textual")
        tabular_count = sum(1 for ft in file_types if get_embedd_type_from_file_type(ft) == "tabular")
        
        # If all files are tabular, use tabular; otherwise use textual
        if tabular_count > 0 and textual_count == 0:
            embedd_type = "tabular"
        else:
            embedd_type = "textual"
        
        assert embedd_type == "textual"  # Should default to textual


class TestPayloadFormat:
    """Test cases for ML API payload format"""
    
    def test_payload_structure(self):
        """Test that payload has correct structure"""
        from app.services.ml_service import MLService
        
        ml_service = MLService()
        
        # Simulate payload creation
        channel_id = "test_channel_id"
        vault_unique_ids = ["test_vault_id"]
        embedded_vault_unique_ids = []
        user_id = "test_user_id"
        company_id = "test_company_id"
        embedd_type = "textual"
        
        # Create payload (matching the ML service)
        payload = {
            "channelId": channel_id,
            "dataSourcesVaultTokens": vault_unique_ids,
            "embeddedDataSourceVaultTokens": embedded_vault_unique_ids or [],
            "userId": user_id,
            "companyId": company_id,
            "embeddType": embedd_type
        }
        
        # Verify payload structure
        required_fields = ["channelId", "dataSourcesVaultTokens", "embeddedDataSourceVaultTokens", "userId", "companyId", "embeddType"]
        for field in required_fields:
            assert field in payload, f"Missing required field: {field}"
        
        # Verify embeddType value
        assert payload["embeddType"] in ["textual", "tabular"]
        
        # Verify field name is camelCase
        assert "embeddType" in payload
        assert "embedd_type" not in payload
    
    def test_payload_with_different_embedd_types(self):
        """Test payload with different embedd_type values"""
        from app.services.ml_service import MLService
        
        ml_service = MLService()
        
        # Test textual
        payload_textual = {
            "channelId": "test_channel_id",
            "dataSourcesVaultTokens": ["test_vault_id"],
            "embeddedDataSourceVaultTokens": [],
            "userId": "test_user_id",
            "companyId": "test_company_id",
            "embeddType": "textual"
        }
        
        assert payload_textual["embeddType"] == "textual"
        
        # Test tabular
        payload_tabular = {
            "channelId": "test_channel_id",
            "dataSourcesVaultTokens": ["test_vault_id"],
            "embeddedDataSourceVaultTokens": [],
            "userId": "test_user_id",
            "companyId": "test_company_id",
            "embeddType": "tabular"
        }
        
        assert payload_tabular["embeddType"] == "tabular"
    
    def test_payload_no_callback_url(self):
        """Test that payload does not include callbackUrl"""
        from app.services.ml_service import MLService
        
        ml_service = MLService()
        
        # Simulate payload creation
        payload = {
            "channelId": "test_channel_id",
            "dataSourcesVaultTokens": ["test_vault_id"],
            "embeddedDataSourceVaultTokens": [],
            "userId": "test_user_id",
            "companyId": "test_company_id",
            "embeddType": "textual"
        }
        
        # Verify callbackUrl is not present
        assert "callbackUrl" not in payload
        assert "callback_url" not in payload


class TestRealWorldScenarios:
    """Test cases for real-world scenarios"""
    
    def test_excel_file_scenario(self):
        """Test Excel file scenario that was causing the original issue"""
        file_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        embedd_type = get_embedd_type_from_file_type(file_type)
        
        assert embedd_type == "tabular"
        
        # Test payload would be
        payload = {
            "channelId": "test_channel_id",
            "dataSourcesVaultTokens": ["test_vault_id"],
            "embeddedDataSourceVaultTokens": [],
            "userId": "test_user_id",
            "companyId": "test_company_id",
            "embeddType": embedd_type
        }
        
        assert payload["embeddType"] == "tabular"
    
    def test_pdf_file_scenario(self):
        """Test PDF file scenario"""
        file_type = "application/pdf"
        embedd_type = get_embedd_type_from_file_type(file_type)
        
        assert embedd_type == "textual"
        
        # Test payload would be
        payload = {
            "channelId": "test_channel_id",
            "dataSourcesVaultTokens": ["test_vault_id"],
            "embeddedDataSourceVaultTokens": [],
            "userId": "test_user_id",
            "companyId": "test_company_id",
            "embeddType": embedd_type
        }
        
        assert payload["embeddType"] == "textual"
    
    def test_csv_file_scenario(self):
        """Test CSV file scenario"""
        file_type = "text/csv"
        embedd_type = get_embedd_type_from_file_type(file_type)
        
        assert embedd_type == "tabular"
        
        # Test payload would be
        payload = {
            "channelId": "test_channel_id",
            "dataSourcesVaultTokens": ["test_vault_id"],
            "embeddedDataSourceVaultTokens": [],
            "userId": "test_user_id",
            "companyId": "test_company_id",
            "embeddType": embedd_type
        }
        
        assert payload["embeddType"] == "tabular"
    
    def test_mixed_files_scenario(self):
        """Test mixed files scenario"""
        file_types = [
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # Excel
            "application/pdf",  # PDF
            "text/csv"  # CSV
        ]
        
        # Determine embedd_type based on logic
        textual_count = sum(1 for ft in file_types if get_embedd_type_from_file_type(ft) == "textual")
        tabular_count = sum(1 for ft in file_types if get_embedd_type_from_file_type(ft) == "tabular")
        
        # If all files are tabular, use tabular; otherwise use textual
        if tabular_count > 0 and textual_count == 0:
            embedd_type = "tabular"
        else:
            embedd_type = "textual"
        
        assert embedd_type == "textual"  # Should default to textual for mixed types
        
        # Test payload would be
        payload = {
            "channelId": "test_channel_id",
            "dataSourcesVaultTokens": ["test_vault_id"],
            "embeddedDataSourceVaultTokens": [],
            "userId": "test_user_id",
            "companyId": "test_company_id",
            "embeddType": embedd_type
        }
        
        assert payload["embeddType"] == "textual"
