"""
Company schemas package (re-exports).

This package replaces the former single-file app/schemas/company.py, split
into create/responses/invitations modules to keep each file under the
Raven 150-line style limit. All public names are re-exported here so
existing `from app.schemas.company import X` imports keep working
unchanged.
"""

from .create import (
    CompanyCreate,
    CompanyCreateSimple,
    CompanyCreateSimpleEncrypted,
    CompanySignupRequest,
    CompanyUpdate,
    CompanyProfileUpdate,
)
from .responses import (
    CompanyResponse,
    CompanyList,
    CompanyStats,
    CompanyCreationResponse,
)
from .invitations import (
    UserInvitation,
    InvitedByUser,
    UserInvitationResponse,
    InvitationAccept,
    InvitationListResponse,
)

__all__ = [
    "CompanyCreate",
    "CompanyCreateSimple",
    "CompanyCreateSimpleEncrypted",
    "CompanySignupRequest",
    "CompanyUpdate",
    "CompanyProfileUpdate",
    "CompanyResponse",
    "CompanyList",
    "CompanyStats",
    "CompanyCreationResponse",
    "UserInvitation",
    "InvitedByUser",
    "UserInvitationResponse",
    "InvitationAccept",
    "InvitationListResponse",
]
