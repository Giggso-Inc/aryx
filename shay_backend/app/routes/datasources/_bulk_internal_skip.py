"""
"Skip, don't fail" signal for the internal/bulk per-item loop (duplicates in
the same thread, unsupported .ics attachments).

Private module: used by _bulk_internal_create_item.py and
bulk_create_internal.py.
"""


class BulkItemSkipped(Exception):
    """Raised for an item that should be recorded in skipped_datasources, not
    failed_datasources (duplicate-in-thread, unsupported .ics extension)."""

    def __init__(self, name: str, reason: str, message: str):
        self.name = name
        self.reason = reason
        self.message = message
        super().__init__(message)
