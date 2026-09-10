"""Oracle Cloud Object Storage file storage provider."""

from typing import Any, Dict

from .base import FileStorageProvider

try:
    from oci.object_storage import ObjectStorageClient
    from oci.config import from_file
    OCI_AVAILABLE = True
except ImportError:
    OCI_AVAILABLE = False


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
