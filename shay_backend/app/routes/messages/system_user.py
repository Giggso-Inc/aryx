"""
System-user lookup/creation, used for AI/system-authored messages.

Split out of the original app/routes/messages.py (2,513 lines) — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5. Shared by
messages_create.create_message (system message_type) and
ml_store.store_ml_messages.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User


async def get_or_create_system_user(db: AsyncSession) -> User:
    """Get or create a system user for system messages"""
    # Check if system user exists
    stmt = select(User).where(User.email_id == settings.SYSTEM_USER_EMAIL)
    result = await db.execute(stmt)
    system_user = result.scalar_one_or_none()

    if not system_user:
        # Create system user if it doesn't exist
        from app.core.auth import generate_user_id

        system_user = User(
            id=generate_user_id(),
            name=settings.SYSTEM_USER_NAME,
            email_id=settings.SYSTEM_USER_EMAIL,
            role=settings.SYSTEM_USER_ROLE,
            is_active=True,
            is_verified=True,
            oauth_provider="system"
        )

        db.add(system_user)
        await db.commit()
        await db.refresh(system_user)

    return system_user
