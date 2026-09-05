"""
Format-specific validators (Kubernetes plain-text log format, cloud/CSV
format) used as fallback acceptance checks by validate_file_content.

Split out of app/utils/file_validation.py — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.
"""

import logging
import re

logger = logging.getLogger(__name__)


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
