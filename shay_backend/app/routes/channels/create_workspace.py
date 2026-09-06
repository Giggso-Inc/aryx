"""
Workspace resolution for create_channel: find-or-validate the workspace a
new channel belongs to, either by explicit workspace_id or by
workspace_tag (creating the workspace on first use of a tag).

Split out of create.py in wave B3 of the Raven style-compliance line-count
pass (see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) to bring
create.py under 150 lines; originally split out of app/routes/channels.py
(2,630 lines) in Phase 5.
"""

from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import generate_workspace_id
from app.models.workspace import Workspace


async def resolve_or_create_workspace(db: AsyncSession, channel_data, user) -> Workspace:
    """Resolve channel_data.workspace_id to an existing workspace, or
    find-or-create the workspace named by channel_data.workspace_tag.
    Caller has already validated that exactly one of the two is set."""
    if channel_data.workspace_id:
        try:
            workspace_uuid = UUID(channel_data.workspace_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid workspace_id format"
            )

        workspace_stmt = select(Workspace).where(
            and_(
                Workspace.id == workspace_uuid,
                Workspace.company_id == user.company_id,
                Workspace.is_active == True
            )
        )
        workspace = (await db.execute(workspace_stmt)).scalar_one_or_none()

        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found or you don't have access to it"
            )
        return workspace

    # workspace_tag path: find existing workspace for this tag, or create it
    workspace_stmt = select(Workspace).where(
        and_(
            Workspace.name == channel_data.workspace_tag,
            Workspace.company_id == user.company_id,
            Workspace.is_active == True
        )
    )
    workspace = (await db.execute(workspace_stmt)).scalar_one_or_none()

    if not workspace:
        workspace = Workspace(
            id=generate_workspace_id(),
            name=channel_data.workspace_tag,
            description=f"Auto-created workspace for tag: {channel_data.workspace_tag}",
            company_id=user.company_id,
            is_public=channel_data.is_public,
            ai_enabled=channel_data.ai_enabled,
            ai_provider="openai",
            ai_model="gpt-4",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(workspace)
        await db.flush()  # Flush to get the workspace ID

    return workspace
