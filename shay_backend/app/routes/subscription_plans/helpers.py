"""Shared helpers for the subscription_plans route package."""

import uuid

from fastapi import HTTPException, status


def validate_uuid(uuid_string: str, field_name: str = "ID") -> uuid.UUID:
    """Validate and return UUID from string, or raise HTTPException if invalid"""
    try:
        return uuid.UUID(uuid_string)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_name} format. Must be a valid UUID."
        )
