"""Provider-selecting facade + process-wide singleton accessor."""

from typing import Any, Dict

from app.core.config import settings
from .aws import AWSFileStorage
from .azure import AzureFileStorage
from .base import FileStorageProvider
from .local import LocalFileStorage
from .oracle import OracleFileStorage


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
