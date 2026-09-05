"""
Approval schemas package (re-exports).

This package replaces the former single-file app/schemas/approval.py,
split into requests/responses/enhanced modules to keep each file under
the Raven 150-line style limit. All public names are re-exported here so
existing `from app.schemas.approval import X` imports keep working
unchanged.
"""

from .requests import (
    ApprovalCreate,
    ApprovalUpdate,
    ApprovalAction,
    ApprovalReassign,
)
from .responses import (
    ApprovalResponse,
    ApprovalWithDetailsResponse,
    ApprovalList,
    ApprovalStats,
)
from .enhanced import (
    ApprovalHistoryItem,
    ApprovalDetails,
    EnhancedApprovalResponse,
    ApprovalCountResponse,
    ApprovalListResponse,
)

__all__ = [
    "ApprovalCreate",
    "ApprovalUpdate",
    "ApprovalAction",
    "ApprovalReassign",
    "ApprovalResponse",
    "ApprovalWithDetailsResponse",
    "ApprovalList",
    "ApprovalStats",
    "ApprovalHistoryItem",
    "ApprovalDetails",
    "EnhancedApprovalResponse",
    "ApprovalCountResponse",
    "ApprovalListResponse",
]
