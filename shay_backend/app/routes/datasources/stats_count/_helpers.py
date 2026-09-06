"""Small helpers shared by the /stats and /count endpoints in this package."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import String, or_
from sqlalchemy.sql.expression import literal

from app.models.datasource import Datasource


def _parse_channel_uuid(channel_id: str):
    try:
        return uuid.UUID(channel_id) if isinstance(channel_id, str) else channel_id
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid channel_id format: {channel_id}"
        )


def _exclude_thread_level():
    return or_(
        Datasource.datasource_metadata.is_(None),
        ~Datasource.datasource_metadata.op("?")(literal("thread_id", type_=String()))
    )
