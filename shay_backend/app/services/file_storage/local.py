"""Local-disk file storage provider."""

import os
from typing import Any, Dict

import aiofiles

from app.core.config import settings
from .base import FileStorageProvider


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
