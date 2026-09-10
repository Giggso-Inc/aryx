"""
Section-header extraction — the shared parsing primitive every validator
in this package builds on.

Split out of app/utils/file_validation.py — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.
"""

import logging
import re
from typing import List, Tuple

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
