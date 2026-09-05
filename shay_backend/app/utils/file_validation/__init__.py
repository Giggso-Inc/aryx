"""
File validation utility for checking log file format and structure.

Package split from the former single-file app/utils/file_validation.py —
see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md:
- headers.py        — extract_section_headers (shared parsing primitive)
- s3.py              — read_from_s3
- format_checks.py   — validate_kubernetes_log_file, validate_cloud_log_file
- validators.py      — validate_log_file, validate_file_content,
                       get_validation_summary (top-level entry points)

Re-exports every name external code imported from
`app.utils.file_validation` before the split (grepped: only
validate_file_content is imported externally, by
app/routes/gg_datasources/upload.py and 4 files under app/routes/datasources/;
every other name is re-exported too for completeness, since test code and
boto3/os patch targets reference this module by its old flat name in
places).
"""

from app.utils.file_validation.format_checks import validate_cloud_log_file, validate_kubernetes_log_file
from app.utils.file_validation.headers import extract_section_headers
from app.utils.file_validation.s3 import read_from_s3
from app.utils.file_validation.validators import get_validation_summary, validate_file_content, validate_log_file

__all__ = [
    "extract_section_headers",
    "read_from_s3",
    "validate_log_file",
    "validate_file_content",
    "get_validation_summary",
    "validate_kubernetes_log_file",
    "validate_cloud_log_file",
]
