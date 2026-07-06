"""
File storage service for handling local and cloud file uploads
"""

import os
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import aiofiles

# Conditional imports for cloud providers
try:
    import boto3
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

try:
    from azure.storage.blob import BlobServiceClient
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False

try:
    import oci
    from oci.object_storage import ObjectStorageClient
    from oci.config import from_file
    OCI_AVAILABLE = True
except ImportError:
    OCI_AVAILABLE = False

from app.core.config import settings


def generate_structured_path(
    company_name: str,
    company_id: str,
    file_type: str,
    original_filename: str,
    base_filename: str,
    file_extension: str,
    current_date: str
) -> str:
    """
    Generate a structured file path based on company and file type
    
    Args:
        company_name: Name of the company
        company_id: ID of the company
        file_type: Type of file (datasource, attachment, commentfile)
        original_filename: Original filename
        base_filename: Filename without extension
        file_extension: File extension
        current_date: Current date string
    
    Returns:
        Structured path: company_name_company_id/file_type/filename_date.ext
    """
    # Clean company name for use in path (remove special characters, replace spaces with underscores)
    clean_company_name = company_name.replace(' ', '_').replace('-', '_').replace('.', '_')
    # Remove any other special characters that might cause issues in file paths
    clean_company_name = ''.join(c for c in clean_company_name if c.isalnum() or c == '_')
    # Remove consecutive underscores
    while '__' in clean_company_name:
        clean_company_name = clean_company_name.replace('__', '_')
    # Remove leading/trailing underscores
    clean_company_name = clean_company_name.strip('_')
    
    # Create the structured path
    structured_path = f"{clean_company_name}_{company_id}/{file_type}/{base_filename}_{current_date}{file_extension}"
    
    return structured_path


class FileStorageProvider(ABC):
    """Abstract base class for file storage providers"""
    
    @abstractmethod
    async def upload_file(self, file_content: bytes, destination_path: str, original_filename: str) -> Dict[str, Any]:
        """Upload file and return storage info"""
        pass
    
    @abstractmethod
    async def download_file(self, file_path: str) -> bytes:
        """Download file and return content"""
        pass
    
    @abstractmethod
    async def delete_file(self, file_path: str) -> bool:
        """Delete file and return success status"""
        pass


class LocalFileStorage(FileStorageProvider):
    """Local file storage implementation"""
    
    def __init__(self, base_dir: str = "uploads"):
        self.base_dir = base_dir
    
    async def upload_file(self, file_content: bytes, destination_path: str, original_filename: str) -> Dict[str, Any]:
        """Upload file to local storage"""
        # Create full path
        full_path = os.path.join(self.base_dir, destination_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        # Write file
        async with aiofiles.open(full_path, 'wb') as f:
            await f.write(file_content)
        
        # Generate URL using LOCAL_FILES_URL from settings
        file_url = f"{settings.LOCAL_FILES_URL.rstrip('/')}/{destination_path}"
        
        return {
            "storage_path": full_path,
            "provider": "local",
            "file_url": file_url,
            "size": len(file_content)
        }
    
    async def download_file(self, file_path: str) -> bytes:
        """Download file from local storage"""
        async with aiofiles.open(file_path, 'rb') as f:
            return await f.read()
    
    async def delete_file(self, file_path: str) -> bool:
        """Delete file from local storage"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            return True
        except Exception:
            return False


class AWSFileStorage(FileStorageProvider):
    """AWS S3 file storage implementation"""
    
    def __init__(self, bucket_name: str, region_name: str = "us-east-1"):
        if not BOTO3_AVAILABLE:
            raise ImportError("boto3 is required for AWS S3 storage. Install it with: pip install boto3")
        
        self.bucket_name = bucket_name
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=region_name
        )
    
    async def upload_file(self, file_content: bytes, destination_path: str, original_filename: str) -> Dict[str, Any]:
        """Upload file to AWS S3"""
        try:
            # Upload to S3
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=destination_path,
                Body=file_content,
                ContentType=self._get_content_type(original_filename)
            )
            
            # Generate URL
            file_url = f"https://{self.bucket_name}.s3.amazonaws.com/{destination_path}"
            
            return {
                "storage_path": destination_path,
                "provider": "aws",
                "file_url": file_url,
                "size": len(file_content),
                "bucket_name": self.bucket_name,
                "region": self.s3_client.meta.region_name
            }
        except Exception as e:
            raise Exception(f"AWS upload failed: {str(e)}")
    
    async def download_file(self, file_path: str) -> bytes:
        """Download file from AWS S3"""
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=file_path)
            return response['Body'].read()
        except Exception as e:
            raise Exception(f"AWS download failed: {str(e)}")
    
    async def delete_file(self, file_path: str) -> bool:
        """Delete file from AWS S3"""
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=file_path)
            return True
        except Exception:
            return False
    
    def _get_content_type(self, filename: str) -> str:
        """Get content type based on file extension"""
        ext = os.path.splitext(filename)[1].lower()
        content_types = {
            '.txt': 'text/plain',
            '.log': 'text/plain',
            '.json': 'application/json',
            '.xml': 'application/xml'
        }
        return content_types.get(ext, 'application/octet-stream')


class AzureFileStorage(FileStorageProvider):
    """Azure Blob Storage implementation"""
    
    def __init__(self, connection_string: str, container_name: str):
        if not AZURE_AVAILABLE:
            raise ImportError("azure-storage-blob is required for Azure storage. Install it with: pip install azure-storage-blob")
        
        self.container_name = container_name
        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    
    async def upload_file(self, file_content: bytes, destination_path: str, original_filename: str) -> Dict[str, Any]:
        """Upload file to Azure Blob Storage"""
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=destination_path
            )
            
            # Upload blob
            blob_client.upload_blob(file_content, overwrite=True)
            
            # Generate URL
            file_url = blob_client.url
            
            return {
                "storage_path": destination_path,
                "provider": "azure",
                "file_url": file_url,
                "size": len(file_content),
                "container_name": self.container_name,
                "account_name": self.blob_service_client.account_name
            }
        except Exception as e:
            raise Exception(f"Azure upload failed: {str(e)}")
    
    async def download_file(self, file_path: str) -> bytes:
        """Download file from Azure Blob Storage"""
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=file_path
            )
            
            download_stream = blob_client.download_blob()
            return download_stream.readall()
        except Exception as e:
            raise Exception(f"Azure download failed: {str(e)}")
    
    async def delete_file(self, file_path: str) -> bool:
        """Delete file from Azure Blob Storage"""
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=file_path
            )
            blob_client.delete_blob()
            return True
        except Exception:
            return False


class OracleFileStorage(FileStorageProvider):
    """Oracle Cloud Object Storage implementation"""
    
    def __init__(self, namespace: str, bucket_name: str, compartment_id: str):
        if not OCI_AVAILABLE:
            raise ImportError("oci is required for Oracle Cloud storage. Install it with: pip install oci")
        
        self.namespace = namespace
        self.bucket_name = bucket_name
        self.compartment_id = compartment_id
        
        # Initialize Oracle client
        config = from_file()  # Load from ~/.oci/config
        self.object_storage_client = ObjectStorageClient(config)
    
    async def upload_file(self, file_content: bytes, destination_path: str, original_filename: str) -> Dict[str, Any]:
        """Upload file to Oracle Cloud Object Storage"""
        try:
            # Upload object
            self.object_storage_client.put_object(
                namespace_name=self.namespace,
                bucket_name=self.bucket_name,
                object_name=destination_path,
                put_object_body=file_content
            )
            
            # Generate URL
            file_url = f"https://objectstorage.{self.namespace}.oraclecloud.com/n/{self.namespace}/b/{self.bucket_name}/o/{destination_path}"
            
            return {
                "storage_path": destination_path,
                "provider": "oracle",
                "file_url": file_url,
                "size": len(file_content),
                "bucket_name": self.bucket_name,
                "namespace": self.namespace,
                "compartment_id": self.compartment_id
            }
        except Exception as e:
            raise Exception(f"Oracle upload failed: {str(e)}")
    
    async def download_file(self, file_path: str) -> bytes:
        """Download file from Oracle Cloud Object Storage"""
        try:
            response = self.object_storage_client.get_object(
                namespace_name=self.namespace,
                bucket_name=self.bucket_name,
                object_name=file_path
            )
            return response.data.content
        except Exception as e:
            raise Exception(f"Oracle download failed: {str(e)}")
    
    async def delete_file(self, file_path: str) -> bool:
        """Delete file from Oracle Cloud Object Storage"""
        try:
            self.object_storage_client.delete_object(
                namespace_name=self.namespace,
                bucket_name=self.bucket_name,
                object_name=file_path
            )
            return True
        except Exception:
            return False


class FileStorageService:
    """Main file storage service that handles different providers"""
    
    def __init__(self):
        self.provider = self._initialize_provider()
    
    def _initialize_provider(self) -> FileStorageProvider:
        """Initialize the appropriate storage provider based on environment"""
        storage_env = settings.FILE_UPLOAD_ENV
        
        if storage_env == 'local':
            return LocalFileStorage(settings.UPLOAD_DIR)
        
        elif storage_env == 'cloud':
            cloud_provider = settings.CLOUD_PROVIDER
            
            if cloud_provider == 'aws':
                bucket_name = settings.AWS_BUCKET_NAME
                region_name = settings.AWS_REGION
                if not bucket_name:
                    raise ValueError("AWS_BUCKET_NAME environment variable is required for AWS storage")
                return AWSFileStorage(bucket_name, region_name)
            
            elif cloud_provider == 'azure':
                connection_string = settings.AZURE_STORAGE_CONNECTION_STRING
                container_name = settings.AZURE_CONTAINER_NAME
                if not connection_string or not container_name:
                    raise ValueError("AZURE_STORAGE_CONNECTION_STRING and AZURE_CONTAINER_NAME environment variables are required for Azure storage")
                return AzureFileStorage(connection_string, container_name)
            
            elif cloud_provider == 'oracle':
                namespace = settings.ORACLE_NAMESPACE
                bucket_name = settings.ORACLE_BUCKET_NAME
                compartment_id = settings.ORACLE_COMPARTMENT_ID
                if not namespace or not bucket_name or not compartment_id:
                    raise ValueError("ORACLE_NAMESPACE, ORACLE_BUCKET_NAME, and ORACLE_COMPARTMENT_ID environment variables are required for Oracle storage")
                return OracleFileStorage(namespace, bucket_name, compartment_id)
            
            else:
                raise ValueError(f"Unsupported cloud provider: {cloud_provider}")
        
        else:
            raise ValueError(f"Unsupported storage environment: {storage_env}")
    
    async def upload_file(self, file_content: bytes, destination_path: str, original_filename: str) -> Dict[str, Any]:
        """Upload file using the configured provider"""
        return await self.provider.upload_file(file_content, destination_path, original_filename)
    
    async def download_file(self, file_path: str) -> bytes:
        """Download file using the configured provider"""
        return await self.provider.download_file(file_path)
    
    async def delete_file(self, file_path: str) -> bool:
        """Delete file using the configured provider"""
        return await self.provider.delete_file(file_path)


# Global instance (lazy initialization)
_file_storage_service = None


def get_file_storage_service() -> FileStorageService:
    """Get the file storage service instance"""
    global _file_storage_service
    if _file_storage_service is None:
        _file_storage_service = FileStorageService()
    return _file_storage_service 