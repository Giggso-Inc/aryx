"""build_approval_context — resolves an approval's channel/workspace/thread
context through its message_id. Split out of the original history_builder.py
(it shares no state with the timeline-building functions there).
"""

from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.models.channel import Channel
from app.models.message import Message, Thread
from app.models.workspace import Workspace


async def build_approval_context(approval: Approval, db: AsyncSession) -> Dict[str, Any]:
    """
    Build context information for an approval by resolving through message_id.

    Args:
        approval (Approval): The approval object
        db (AsyncSession): Database session

    Returns:
        Dict[str, Any]: Context information
    """
    context = {}

    if not (hasattr(approval, 'message_id') and approval.message_id):
        return context

    try:
        msg_stmt = select(Message).where(Message.id == approval.message_id)
        msg_result = await db.execute(msg_stmt)
        msg = msg_result.scalar_one_or_none()

        if not msg:
            return context

        # Channel context
        if msg.channel_id:
            channel_stmt = select(Channel).where(Channel.id == msg.channel_id)
            channel_result = await db.execute(channel_stmt)
            channel = channel_result.scalar_one_or_none()

            if channel:
                # Load workspace
                if channel.workspace_id:
                    workspace_stmt = select(Workspace).where(Workspace.id == channel.workspace_id)
                    workspace_result = await db.execute(workspace_stmt)
                    workspace = workspace_result.scalar_one_or_none()

                    if workspace:
                        context['workspace'] = {
                            'id': str(workspace.id),
                            'name': workspace.name,
                            'description': workspace.description
                        }

                context['channel'] = {
                    'id': str(channel.id),
                    'name': channel.name,
                    'description': channel.description,
                    'type': 'public' if channel.is_public else 'private',
                    'is_private': not channel.is_public
                }

        # Thread context
        if msg.thread_id:
            thread_stmt = select(Thread).where(Thread.id == msg.thread_id)
            thread_result = await db.execute(thread_stmt)
            thread = thread_result.scalar_one_or_none()

            if thread:
                context['thread'] = {
                    'id': str(thread.id),
                    'title': thread.title,
                    'description': thread.description
                }

    except Exception as e:
        print(f"Error building approval context from message: {e}")

    return context
