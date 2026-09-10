"""
Pre-upload guard clauses for POST /from-upload: channel lookup + access
check, duplicate-name check, filename check, and company lookup.

Private module: split out of from_upload.py (Raven style-compliance,
wave B4) — these are pure validation/lookup steps with no side effects
beyond raising an HTTPException, independent of the upload+persist
pipeline that follows.
"""

from typing import Optional, Tuple

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import Channel
from app.models.company import Company
from app.models.datasource import Datasource


async def validate_from_upload_request(
    db: AsyncSession,
    user,
    channel_id: str,
    name: Optional[str],
    file: UploadFile,
) -> Tuple[Channel, Company]:
    """Run every pre-upload guard clause; return (channel, company) on success."""
    stmt = select(Channel).where(Channel.id == channel_id)
    result = await db.execute(stmt)
    channel = result.scalar_one_or_none()

    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    # Check permissions
    if not channel.is_accessible_by_user(user.company_id, user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to channel")

    # Check for duplicate datasource in the same channel (if name provided)
    if name:
        existing_datasource_stmt = select(Datasource).where(
            and_(Datasource.name == name, Datasource.channel_id == channel_id)
        )
        existing_datasource_result = await db.execute(existing_datasource_stmt)
        if existing_datasource_result.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Datasource with name '{name}' already exists in this channel"
            )

    # Validate file
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File name is required")

    # Get company information
    company_stmt = select(Company).where(Company.id == user.company_id)
    company_result = await db.execute(company_stmt)
    company = company_result.scalar_one_or_none()

    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    return channel, company
