"""
Channel Access Authorization Utilities

This module provides helper functions to check if a user has access to a channel.
Access is granted if:
1. User is an active member of the channel (checked via gg_channel_members table)
   - Channel admins (role == "admin" in gg_channel_members) can view their channel
   - Channel users (role == "user" in gg_channel_members) can view their channel

Note: Super admin check is commented out for now. When needed, check gg_users table for is_root_admin (boolean column)

Author: Auto-generated
Date: 2025-01-XX
Version: 1.0.0

Package split from the former single-file app/utils/channel_access.py — see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md:
- by_channel.py — check_channel_access (direct membership check)
- by_thread.py  — check_channel_access_by_thread (resolves thread -> channel,
                  then delegates to check_channel_access)

Both are imported externally (app/routes/datasources/list_datasources.py,
app/routes/datasources/embedding_status.py, app/routes/channels/detail.py,
app/routes/channels/members_single.py, app/routes/approvals/list.py,
app/routes/tasks/_list_tasks_helpers.py) and are re-exported here unchanged.
"""

from app.utils.channel_access.by_channel import check_channel_access
from app.utils.channel_access.by_thread import check_channel_access_by_thread

__all__ = [
    "check_channel_access",
    "check_channel_access_by_thread",
]
