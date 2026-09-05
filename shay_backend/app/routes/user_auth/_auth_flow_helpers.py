"""
Shared helpers for register.py and login.py.

Split out further from the original registration.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 follow-up). Both
register_user and login_user need to look up a user's company, find-or-create
that company's default workspace, and build the JWT token payload — these
three helpers were duplicated near-verbatim in both endpoints, so they are
consolidated here rather than kept in "the same new file" per endpoint.
"""

import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select, and_

from app.models.company import Company
from app.models.workspace import Workspace


async def _get_company_or_404(db, company_id) -> Company:
    """Fetch a Company by id or raise 404 Company not found."""
    stmt = select(Company).where(Company.id == company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    return company


async def _get_or_create_default_workspace(db, company, user) -> Workspace:
    """Return the company's default workspace, creating it if it doesn't exist."""
    stmt = select(Workspace).where(
        and_(
            Workspace.company_id == user.company_id,
            Workspace.name == company.name,
            Workspace.is_active == True
        )
    )
    result = await db.execute(stmt)
    default_workspace = result.scalar_one_or_none()

    if not default_workspace:
        workspace_id = uuid.uuid4()
        default_workspace = Workspace(
            id=workspace_id,
            name=company.name,
            description=f"Default workspace for {company.name}",
            company_id=user.company_id,
            created_by=user.id,
            is_active=True,
            is_public=False,
            ai_enabled=True,
            ai_provider="openai",
            ai_model="gpt-4",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(default_workspace)
        await db.commit()
        await db.refresh(default_workspace)

    return default_workspace


def _build_token_data(user) -> dict:
    """Build the JWT payload dict shared by register/login token issuance."""
    return {
        "sub": str(user.id),
        "email": user.email_id,
        "role": user.role,
        "company_id": str(user.company_id),
        "type": "access"
    }
