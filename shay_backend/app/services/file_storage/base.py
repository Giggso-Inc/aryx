"""Shared abstract provider interface + structured-path naming helper."""

from abc import ABC, abstractmethod
from typing import Any, Dict


def generate_structured_path(
    company_name: str,
    company_id: str,
    file_type: str,
    original_filename: str,
    base_filename: str,
    file_extension: str,
    current_date: str,
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
