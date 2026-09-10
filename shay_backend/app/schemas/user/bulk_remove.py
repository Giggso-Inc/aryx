"""
Bulk user removal request/response schemas.

Split out of the former app/schemas/user.py during Phase 5a file-size
compliance work. See app/schemas/user/__init__.py for the full package
layout and re-export list.
"""

from typing import List
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class BulkRemoveUsersRequest(BaseModel):
    user_ids: list[UUID]

    @field_validator("user_ids")
    @classmethod
    def validate_user_ids(cls, v) -> List[UUID]:
        if not v:
            raise ValueError("user_ids cannot be empty")
        if len(v) > 100:
            raise ValueError("Cannot remove more than 100 users at once")
        return list(set(v))


class BulkRemoveUsersResponse(BaseModel):
    message: str = Field(..., description="Success message")
    removed_user_ids: list[str] = Field(..., description="User IDs that were successfully removed")
    not_found_user_ids: list[str] = Field(default_factory=list, description="User IDs that were not found in the company")
    revoked_channel_memberships: int = Field(..., description="Number of revoked channel memberships")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "3 user(s) removed from company successfully",
                "removed_user_ids": ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"],
                "not_found_user_ids": ["33333333-3333-3333-3333-333333333333"],
                "revoked_channel_memberships": 5
            }
        }
