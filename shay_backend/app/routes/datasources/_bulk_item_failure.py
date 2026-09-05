"""
Shared "expected per-item failure" exception for the from-upload bulk loop.

Private module: used by _from_upload_bulk_item.py and
_from_upload_bulk_persist.py to report an expected failure (channel not
found, access denied, duplicate name, vault integration failure, etc.) up
to from_upload_bulk.py's loop, which appends {"name", "error"} to
failed_datasources with the exact same message text as the original inline
try/except-per-item code.
"""


class BulkItemFailure(Exception):
    """Raised for an expected, per-item failure in the from-upload bulk loop."""

    def __init__(self, name: str, error: str):
        self.name = name
        self.error = error
        super().__init__(error)
