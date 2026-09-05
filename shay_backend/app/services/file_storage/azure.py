"""Azure Blob Storage file storage provider."""

from typing import Any, Dict

from .base import FileStorageProvider

try:
    from azure.storage.blob import BlobServiceClient
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False


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
