"""
Per-row CSV upsert logic for the bulk-csv channel-members endpoint.

Split out of members_bulk.py during the Raven style-compliance line-count
pass (wave B2) — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md. Pure
DB upsert logic with no commit/audit-log side effects, so it splits cleanly
from the orchestration in members_bulk.py (which still owns the commit and
the audit_log_write call, so the test's patch on
"app.routes.channels.members_bulk.audit_log_write" keeps working).
"""

from datetime import datetime
from typing import List, Tuple

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import generate_channel_id
from app.models.user import User
from app.models.channel_member import ChannelMember


async def upsert_members_from_csv(
    db: AsyncSession,
    channel,
    csv_data: List[Tuple[str, str]],
) -> Tuple[List[ChannelMember], List[ChannelMember], List[str], List[str]]:
    """Process each (gmail_id, role) row: add new members, update existing
    members' roles if different, and collect errors/already-member notes.

    Returns (created_members, new_members, errors, already_members).
    created_members includes both newly-added and role-updated members;
    new_members is the subset that are brand new (for notifications).
    """
    created_members: List[ChannelMember] = []
    new_members: List[ChannelMember] = []
    errors: List[str] = []
    already_members: List[str] = []

    for gmail_id, role in csv_data:
        try:
            user_stmt = select(User).where(
                and_(
                    User.email_id == gmail_id,
                    User.company_id == channel.company_id,
                    User.is_active == True
                )
            )
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()

            if not user:
                errors.append(f"Email ID '{gmail_id}' does not exist in the database")
                continue

            existing_stmt = select(ChannelMember).where(
                and_(
                    ChannelMember.channel_id == channel.id,
                    ChannelMember.user_id == user.id
                )
            )
            existing_result = await db.execute(existing_stmt)
            existing = existing_result.scalar_one_or_none()

            if existing:
                if existing.role != role:
                    existing.role = role
                    existing.updated_at = datetime.utcnow()
                    created_members.append(existing)
                else:
                    already_members.append(f"User {gmail_id} already in channel with {role} role")
            else:
                member = ChannelMember(
                    id=generate_channel_id(),
                    channel_id=channel.id,
                    user_id=user.id,
                    role=role,
                    permissions={},
                    is_active=True,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(member)
                created_members.append(member)
                new_members.append(member)

        except Exception as e:
            errors.append(f"Error processing user {gmail_id}: {str(e)}")
            continue

    return created_members, new_members, errors, already_members
