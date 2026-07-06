"""
ML API Service for handling embedding requests
"""

import httpx
import asyncio
import json
from typing import List, Dict, Any, Optional
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


def extract_table_names_from_datasources(datasources: List[Any]) -> List[str]:
    """
    Extracts all table names from a list of datasources (dictionaries or ORM models).
    
    Args:
        datasources: List of datasource dicts or ORM model objects.
                    Each should have either:
                    - 'config' dict with 'tableName' key, OR
                    - 'datasource_metadata' dict with 'tableName' key
    
    Returns:
        List of unique table names found.
    """
    table_names = []
    
    for ds in datasources:
        table_name = None
        
        # Handle dictionary format
        if isinstance(ds, dict):
            # Check config first
            if "config" in ds and isinstance(ds["config"], dict):
                table_name = ds["config"].get("tableName")
            # Fall back to datasource_metadata
            if not table_name and "datasource_metadata" in ds and isinstance(ds["datasource_metadata"], dict):
                table_name = ds["datasource_metadata"].get("tableName")
        else:
            # Handle ORM model format (e.g., Datasource model)
            if hasattr(ds, "datasource_metadata") and isinstance(ds.datasource_metadata, dict):
                table_name = ds.datasource_metadata.get("tableName")
            elif hasattr(ds, "config") and isinstance(ds.config, dict):
                table_name = ds.config.get("tableName")
        
        if table_name:
            table_names.append(table_name)
    
    # Return unique table names
    return list(set(table_names))


def get_embedd_type_from_file_type(file_type: str, storage_type: str = None, provider: str = None) -> str:
    """
    Determine embedd_type based on file_type, storage_type, and provider
    
    Args:
        file_type: MIME type or file extension
        storage_type: Storage type (e.g., "database", "cloud", "local", "app")
        provider: Provider/database type (e.g., "mysql", "postgresql", "snowflake", etc.)
        
    Returns:
        "textual" for text-based files, "tabular" for structured data files,
        "tabular" for all database datasources
    """
   
    if storage_type == "database":
        return "tabular"
    
    # If no file_type provided and not a database, default to textual
    if not file_type:
        return "textual"
    
    # Convert to lowercase for case-insensitive comparison
    file_type_lower = file_type.lower()
    
    # Textual file types
    textual_types = [
        'text/plain', 'text/html', 'text/css', 'text/javascript',
        'application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'application/rtf', 'text/rtf'
    ]
    
    # Tabular file types
    tabular_types = [
        'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/vnd.google-apps.spreadsheet',
        'text/csv', 'application/csv', 'application/json', 'text/json'
    ]
    
    # Check MIME types first
    is_textual = False
    is_tabular = False
    
    if file_type_lower in textual_types:
        is_textual = True
    elif file_type_lower in tabular_types:
        is_tabular = True
    
    # Check file extensions (common patterns) if not already determined
    if not is_textual and not is_tabular:
        if file_type_lower in ['txt', 'pdf', 'doc', 'docx', 'ppt', 'pptx', 'rtf', 'html', 'htm', 'css', 'js']:
            is_textual = True
        elif file_type_lower in ['xls', 'xlsx', 'csv', 'json']:
            is_tabular = True
    
    # Determine base embedd_type
    if is_textual:
        return "textual"
    elif is_tabular:
        return "tabular"
    else:
        # Default to textual if file type cannot be determined
        return "textual"


class MLService:
    """Service for interacting with ML API for embedding processing"""
    
    def __init__(self):
        self.ml_api_url = getattr(settings, 'ML_API_URL', 'https://dev-fourd.shay-ai.com')
        self.ml_api_key = getattr(settings, 'ML_API_KEY', '')
        self.timeout = None 
    
    async def request_embedding_processing(
        self, 
        vault_unique_ids: List[str],
        user_id: str,
        company_id: str,
        channel_id: str,
        embedded_vault_unique_ids: List[str] = None,
        jwt_token: str = None,
        embedd_type: str = "textual",
        table_name: Optional[str] = None,
        table_names: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
        openai_vault_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Request embedding processing from ML API
        
        Args:
            vault_unique_ids: List of vault unique IDs to process
            user_id: User ID who requested the processing
            company_id: Company ID for context
            channel_id: Channel ID from the request
            embedded_vault_unique_ids: List of already embedded vault unique IDs
            jwt_token: JWT token for authentication (optional, falls back to ML_API_KEY)
            embedd_type: Type of embedding ("textual" or "tabular")
            table_name: Optional table name for database datasources
            thread_id: Optional thread ID for thread-level embeddings (internal/bulk); when set, storage is thread-scoped
            openai_vault_token: Optional vault_unique_id from gg_vault (vault_type='gpt_token') for the company; sent as openaiVaultToken to ML API
            
        Returns:
            Dict containing the response from ML API
        """
        # Prepare payload with camelCase and new fields
        payload = {
            "channelId": channel_id,
            "dataSourcesVaultTokens": vault_unique_ids,
            "embeddedDataSourceVaultTokens": embedded_vault_unique_ids or [],
            "userId": user_id,
            "companyId": company_id,
            "embeddType": embedd_type
        }
        # Include threadId for thread-level embedding storage (internal/bulk API)
        if thread_id:
            payload["threadId"] = thread_id
        # Add table_names to payload if provided, otherwise add table_name if provided
        if table_names:
            payload["tableNames"] = table_names
        elif table_name:
            payload["tableName"] = table_name
        # Add OpenAI vault token from gg_vault (gpt_token) for ML layer when available
        if openai_vault_token:
            payload["openaiVaultToken"] = openai_vault_token
        
        # Prepare headers - use JWT token if provided, otherwise fall back to ML_API_KEY
        auth_token = jwt_token if jwt_token else settings.ML_API_KEY
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}" if auth_token else ""
        }
        
        # Construct full URL
        full_url = f"{self.ml_api_url}/shay/email/embeddings"
        
        # Log ML API details BEFORE making the request
        logger.info("=" * 80)
        logger.info("🚀 ML API REQUEST - EMBEDDING PROCESSING")
        logger.info("=" * 80)
        logger.info(f"📡 ML API URL: {full_url}")
        logger.info(f"🔑 Auth Token: {'JWT Token (***' + auth_token[-4:] + ')' if jwt_token else ('API Key (***' + self.ml_api_key[-4:] + ')' if self.ml_api_key else 'NOT SET')}")
        logger.info(f"⏱️  Timeout: {self.timeout} seconds")
        logger.info(f"📦 Payload: {json.dumps(payload, indent=2)}")
        logger.info(f"📋 Headers: {json.dumps({k: v if k != 'Authorization' else 'Bearer ***' for k, v in headers.items()}, indent=2)}")
        logger.info("=" * 80)
        logger.info("🔄 Attempting to connect to ML API...")
        logger.info("=" * 80)
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    full_url,
                    json=payload,
                    headers=headers
                )
                
                # Log response details
                logger.info("=" * 80)
                logger.info("📥 ML API RESPONSE")
                logger.info("=" * 80)
                logger.info(f"📊 Status Code: {response.status_code}")
                logger.info(f"📋 Response Headers: {dict(response.headers)}")
                logger.info(f"📄 Response Body: {response.text}")
                logger.info("=" * 80)
                
                if response.status_code == 200:
                    try:
                        result = response.json()
                        logger.info(f"✅ Successfully requested embedding processing for {len(vault_unique_ids)} datasources")
                        logger.info(f"📊 ML API Response Data: {json.dumps(result, indent=2)}")
                        return {
                            "success": True,
                            "message": "Embedding processing requested successfully",
                            "data": result
                        }
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Failed to parse ML API response as JSON: {e}")
                        return {
                            "success": False,
                            "message": "Invalid JSON response from ML API",
                            "error": f"JSON decode error: {e}"
                        }
                else:
                    logger.error(f"❌ ML API returned error: {response.status_code} - {response.text}")
                    return {
                        "success": False,
                        "message": f"ML API error: {response.status_code}",
                        "error": response.text
                    }
                    
        except httpx.TimeoutException:
            logger.error("=" * 80)
            logger.error("⏰ ML API TIMEOUT ERROR")
            logger.error("=" * 80)
            logger.error(f"⏱️  Timeout after {self.timeout} seconds")
            logger.error(f"📡 URL: {full_url}")
            logger.error(f"📦 Payload that failed: {json.dumps(payload, indent=2)}")
            logger.error(f"📋 Headers that failed: {json.dumps({k: v if k != 'Authorization' else 'Bearer ***' for k, v in headers.items()}, indent=2)}")
            logger.error("=" * 80)
            return {
                "success": False,
                "message": "Timeout while calling ML API",
                "error": "Request timed out"
            }
        except httpx.RequestError as e:
            logger.error("=" * 80)
            logger.error("🌐 ML API REQUEST ERROR")
            logger.error("=" * 80)
            logger.error(f"📡 URL: {full_url}")
            logger.error(f"❌ Error: {str(e)}")
            logger.error(f"🔍 Error Type: {type(e).__name__}")
            logger.error(f"📦 Payload that failed: {json.dumps(payload, indent=2)}")
            logger.error(f"📋 Headers that failed: {json.dumps({k: v if k != 'Authorization' else 'Bearer ***' for k, v in headers.items()}, indent=2)}")
            logger.error("=" * 80)
            return {
                "success": False,
                "message": "Failed to connect to ML API",
                "error": str(e)
            }
        except Exception as e:
            logger.error("=" * 80)
            logger.error("💥 ML API UNEXPECTED ERROR")
            logger.error("=" * 80)
            logger.error(f"📡 URL: {full_url}")
            logger.error(f"❌ Error: {str(e)}")
            logger.error(f"🔍 Error Type: {type(e).__name__}")
            logger.error(f"📦 Payload that failed: {json.dumps(payload, indent=2)}")
            logger.error(f"📋 Headers that failed: {json.dumps({k: v if k != 'Authorization' else 'Bearer ***' for k, v in headers.items()}, indent=2)}")
            logger.error("=" * 80)
            return {
                "success": False,
                "message": "Unexpected error occurred",
                "error": str(e)
            }
    
    async def check_embedding_status(
        self, 
        vault_unique_ids: List[str],
        jwt_token: str = None
    ) -> Dict[str, Any]:
        """
        Check the status of embedding processing
        
        Args:
            vault_unique_ids: List of vault unique IDs to check
            
        Returns:
            Dict containing the status information
        """
        # Prepare payload
        payload = {
            "vault_unique_ids": vault_unique_ids
        }
        
        # Prepare headers - use JWT token if provided, otherwise fall back to ML_API_KEY
        auth_token = jwt_token if jwt_token else self.ml_api_key
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}" if auth_token else ""
        }
        
        # Construct full URL
        full_url = f"{self.ml_api_url}/api/v1/embedding/status"
        
        # Log ML API details BEFORE making the request
        logger.info("=" * 80)
        logger.info("🔍 ML API REQUEST - STATUS CHECK")
        logger.info("=" * 80)
        logger.info(f"📡 ML API URL: {full_url}")
        logger.info(f"🔑 Auth Token: {'JWT Token (***' + auth_token[-4:] + ')' if jwt_token else ('API Key (***' + self.ml_api_key[-4:] + ')' if self.ml_api_key else 'NOT SET')}")
        logger.info(f"⏱️  Timeout: {self.timeout} seconds")
        logger.info(f"📦 Payload: {json.dumps(payload, indent=2)}")
        logger.info(f"📋 Headers: {json.dumps({k: v if k != 'Authorization' else 'Bearer ***' for k, v in headers.items()}, indent=2)}")
        logger.info("=" * 80)
        logger.info("🔄 Attempting to connect to ML API...")
        logger.info("=" * 80)
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    full_url,
                    params=payload,
                    headers=headers
                )
                
                # Log response details
                logger.info("=" * 80)
                logger.info("📥 ML API STATUS RESPONSE")
                logger.info("=" * 80)
                logger.info(f"📊 Status Code: {response.status_code}")
                logger.info(f"📋 Response Headers: {dict(response.headers)}")
                logger.info(f"📄 Response Body: {response.text}")
                logger.info("=" * 80)
                
                if response.status_code == 200:
                    try:
                        result = response.json()
                        logger.info(f"✅ Successfully checked embedding status for {len(vault_unique_ids)} datasources")
                        logger.info(f"📊 ML API Status Data: {json.dumps(result, indent=2)}")
                        return {
                            "success": True,
                            "data": result
                        }
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Failed to parse ML API status response as JSON: {e}")
                        return {
                            "success": False,
                            "message": "Invalid JSON response from ML API",
                            "error": f"JSON decode error: {e}"
                        }
                else:
                    logger.error(f"❌ ML API status check returned error: {response.status_code} - {response.text}")
                    return {
                        "success": False,
                        "message": f"ML API error: {response.status_code}",
                        "error": response.text
                    }
                    
        except Exception as e:
            logger.error("=" * 80)
            logger.error("💥 ML API STATUS CHECK ERROR")
            logger.error("=" * 80)
            logger.error(f"📡 URL: {full_url}")
            logger.error(f"❌ Error: {str(e)}")
            logger.error(f"🔍 Error Type: {type(e).__name__}")
            logger.error(f"📦 Payload that failed: {json.dumps(payload, indent=2)}")
            logger.error(f"📋 Headers that failed: {json.dumps({k: v if k != 'Authorization' else 'Bearer ***' for k, v in headers.items()}, indent=2)}")
            logger.error("=" * 80)
            return {
                "success": False,
                "message": "Failed to check embedding status",
                "error": str(e)
            }
    
    async def delete_embeddings(
        self,
        channel_id: str,
        data_sources_vault_tokens: Optional[List[str]] = None,
        embedding_type: str = "textual",
        jwt_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Delete embeddings from ML API
        
        Args:
            channel_id: Channel ID
            data_sources_vault_tokens: List of vault unique IDs to delete embeddings for (optional)
            embedding_type: Type of embedding ("textual" or "tabular")
            jwt_token: JWT token for authentication (optional, falls back to ML_API_KEY)
            
        Returns:
            Dict containing the response from ML API with success/error status
        """
        # Prepare payload with camelCase
        payload = {
            "channelId": channel_id,
            "dataSourcesVaultTokens": data_sources_vault_tokens if data_sources_vault_tokens else None,
            "embeddingType": embedding_type
        }
        
        # Prepare headers - use JWT token if provided, otherwise fall back to ML_API_KEY
        auth_token = jwt_token if jwt_token else self.ml_api_key
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}" if auth_token else ""
        }
        
        full_url = f"{self.ml_api_url}/dataai/shay/deleteEmbeddings"
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    full_url,
                    json=payload,
                    headers=headers
                )
                
                if response.status_code == 200:
                    try:
                        result = response.json()
                        logger.info(f" Successfully deleted embeddings for channel {channel_id}")
                        logger.info(f"ML API Response Data: {json.dumps(result, indent=2)}")
                        return {
                            "success": True,
                            "message": "Embeddings deleted successfully",
                            "data": result
                        }
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse ML API response as JSON: {e}")
                        return {
                            "success": False,
                            "message": "Invalid JSON response from ML API",
                            "error": f"JSON decode error: {e}"
                        }
                else:
                    logger.error(f" ML API returned error: {response.status_code} - {response.text}")
                    return {
                        "success": False,
                        "message": f"ML API error: {response.status_code}",
                        "error": response.text
                    }
                    
        except httpx.TimeoutException:
            return {
                "success": False,
                "message": "Timeout while calling ML API",
                "error": "Request timed out"
            }
        except httpx.RequestError as e:
            return {
                "success": False,
                "message": "Failed to connect to ML API",
                "error": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "message": "Unexpected error occurred",
                "error": str(e)
            }


# Global instance
ml_service = MLService()
