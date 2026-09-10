"""
@mention parsing and user lookup helpers.

Split out of the former app/routes/messages/mentions.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5 / wave B2.
"""

import re
from typing import List, Set

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


def parse_mentions_from_content(content: str) -> Set[str]:
    """
    Parse mentions from message content.
    Extracts @username patterns from the content.
    Mentions use user names, not emails.
    Handles formats like:
    - @username

    Args:
        content: Message content string

    Returns:
        Set of mentioned user names (without @ symbol)
    """
    if not content:
        return set()

    # Pattern to match @username
    # Matches @ followed by alphanumeric characters, dots, hyphens, underscores
    # We'll extract each @mention separately
    mention_pattern = r'@([a-zA-Z0-9._-]+)'
    mentions = re.findall(mention_pattern, content)

    # Return unique mentions as a set
    return set(mentions)


async def get_users_by_mentions(mentions: Set[str], db: AsyncSession) -> List[User]:
    """
    Find users by their name from mentions.
    Mentions in content use user names, not emails.

    Args:
        mentions: Set of mention identifiers (user names)
        db: Database session

    Returns:
        List of User objects that match the mentions (unique users only)
    """
    if not mentions:
        return []

    found_user_ids = set()  # Track found user IDs to avoid duplicates
    users = []

    for mention in mentions:
        # Find users by name (case-insensitive matching)
        # Try exact match first
        stmt = select(User).where(func.lower(User.name) == func.lower(mention))
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if user and user.id not in found_user_ids:
            users.append(user)
            found_user_ids.add(user.id)
            continue

        # If exact match not found, try partial match (contains)
        stmt = select(User).where(func.lower(User.name).contains(func.lower(mention)))
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if user and user.id not in found_user_ids:
            users.append(user)
            found_user_ids.add(user.id)

    return users
