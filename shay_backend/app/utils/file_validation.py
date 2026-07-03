"""
File validation utility for checking log file format and structure
"""

import logging
import re
import boto3
import tempfile
import os
from typing import Dict, Any, Tuple, List

logger = logging.getLogger(__name__)


def extract_section_headers(file_content: str) -> Tuple[List[str], List[str]]:
    """
    Extracts section headers from the file content using the given regex pattern.
    Returns a tuple of (headers, lines).
    """
    try:
        section_pattern = r"------ [A-Z]+ .*\(.*\) ------"
        lines = file_content.split('\n')
        
        headers = []
        for line in lines:
            if re.search(section_pattern, line):
                headers.append(line.strip())
                logger.debug(f"Found header: {line.strip()}")
        
        return headers, lines
    except Exception as e:
        logger.exception(f"An error occurred while extracting section headers: {e}")
        return [], []


def read_from_s3(bucket: str, object_name: str, access_key: str, secret_key: str) -> str:
    """
    Read the file from S3 and return the content
    """
    try:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key
        )
        
        response = s3_client.get_object(Bucket=bucket, Key=object_name)
        return response["Body"].read().decode("utf-8")
    except Exception as e:
        logger.exception(f"Error reading from S3: {e}")
        raise


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


def validate_kubernetes_log_file(file_content: bytes, filename: str) -> bool:
    """
    Validate Kubernetes log file content
    """

    content_str = file_content.decode('utf-8')

    log_lines = content_str.split('\n')

    # Regex to match standard Python log format
    LOG_PATTERN = re.compile(
        r"^(?P<asctime>.+?) - (?P<levelname>[A-Z]+) - "
        r"(?P<filename>\w+\.\w+):(?P<lineno>\d+) - (?P<message>.*)$"
    )
    validation_results = []
    for line in log_lines:
        if LOG_PATTERN.match(line):
            # logger.info(f"Valid Kubernetes log line: {line}")
            validation_results.append(True)
        else:
            # logger.warning(f"Invalid Kubernetes log line: {line}")
            validation_results.append(False)
    # logger.info(f"Validation results: {validation_results}")
    if any(validation_results):
        logger.info(f"Kubernetes log file {filename} validation successful.")
        return True
    else:
        return False



def validate_cloud_log_file(file_content: bytes, filename: str) -> bool:
    """
    Validate cloud log file content
    """
    try:
        if filename.endswith('.csv'):
            return True
    except Exception as e:
        logger.exception(f"Error validating cloud log file {filename}: {e}")
        return False
    return False
