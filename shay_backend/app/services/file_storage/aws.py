"""AWS S3 file storage provider."""

import os
from typing import Any, Dict

from app.core.config import settings
from .base import FileStorageProvider

try:
    import boto3
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False


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
