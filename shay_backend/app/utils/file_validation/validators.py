"""
Top-level validation entry points that compose headers/s3/format_checks:
validate_log_file (storage-aware: local disk or S3), validate_file_content
(bytes-in, used for uploaded files), and get_validation_summary.

Split out of app/utils/file_validation.py — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.
"""

import logging
import tempfile
import os
from typing import Dict, Any

from app.utils.file_validation.format_checks import validate_cloud_log_file, validate_kubernetes_log_file
from app.utils.file_validation.headers import extract_section_headers
from app.utils.file_validation.s3 import read_from_s3

logger = logging.getLogger(__name__)


def validate_log_file(input_data: Dict[str, Any]) -> bool:
    """
    Validate the log file and return the result
    """
    try:
        storage_type = input_data.get("storage_type")

        if storage_type == "local":
            file_path = input_data.get("file_path")
            if not file_path or not os.path.exists(file_path):
                logger.warning(f"Local file not found: {file_path}")
                return False

            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()

            headers, _ = extract_section_headers(content)
            return len(headers) > 0

        elif storage_type == "cloud" and input_data.get("storage_provider") == "s3":
            bucket_name = input_data.get("bucket_name")
            access_key = input_data.get("access_key")
            secret_key = input_data.get("secret_key")
            s3_key = input_data.get("s3_key")

            if not all([bucket_name, access_key, secret_key, s3_key]):
                logger.warning("Missing required S3 parameters")
                return False

            content_from_s3 = read_from_s3(bucket_name, s3_key, access_key, secret_key)

            # Create a temporary file for validation
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write(content_from_s3)
                temp_file_path = f.name

            try:
                headers, _ = extract_section_headers(content_from_s3)
                return len(headers) > 0
            finally:
                # Clean up temporary file
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
        else:
            logger.warning(f"Unsupported storage type: {storage_type}")
            return False

    except Exception as e:
        logger.exception(f"Error during file validation: {e}")
        return False


def validate_file_content(file_content: bytes, filename: str) -> bool:
    """
    Validate file content directly from bytes (for uploaded files)
    """
    try:
        # Decode content as UTF-8
        content_str = file_content.decode('utf-8')

        # Extract section headers
        headers, _ = extract_section_headers(content_str)
        kubernetes_validation = validate_kubernetes_log_file(file_content, filename)
        cloud_validation = validate_cloud_log_file(file_content, filename)

        if len(headers) == 0 and not kubernetes_validation and not cloud_validation:
            logger.warning(f"No valid section headers found in file: {filename}")
            return False

        logger.info(f"File {filename} validation successful. Found {len(headers)} section headers.")
        return True

    except UnicodeDecodeError:
        logger.error(f"File {filename} is not valid UTF-8 text")
        return False
    except Exception as e:
        logger.exception(f"Error validating file {filename}: {e}")
        return False


def get_validation_summary(file_content: bytes, filename: str) -> Dict[str, Any]:
    """
    Get detailed validation summary for a file
    """
    try:
        content_str = file_content.decode('utf-8')
        headers, lines = extract_section_headers(content_str)

        return {
            "filename": filename,
            "is_valid": len(headers) > 0,
            "section_headers_count": len(headers),
            "total_lines": len(lines),
            "section_headers": headers[:10],  # Limit to first 10 headers
            "validation_message": f"Found {len(headers)} section headers" if len(headers) > 0 else "No valid section headers found"
        }
    except Exception as e:
        logger.exception(f"Error generating validation summary for {filename}: {e}")
        return {
            "filename": filename,
            "is_valid": False,
            "section_headers_count": 0,
            "total_lines": 0,
            "section_headers": [],
            "validation_message": f"Validation error: {str(e)}"
        }
