"""
Message schemas package (re-exports).

This package replaces the former single-file app/schemas/message.py, split
into shared / message_requests / message_responses / thread_requests /
thread_responses modules to keep each file under the Raven 150-line style
limit. All public names are re-exported here so existing
`from app.schemas.message import X` imports keep working unchanged.
"""

from .shared import (
    UserBean,
    AttachmentReference,
    AttachmentDetails,
    Citation,
)
from .message_requests import (
    MessageCreate,
    MessageUpdate,
    MessageDelete,
    HideThreadMessagesBody,
    HideThreadMessagesResponse,
)
from .message_responses import (
    MessageResponse,
    MessageList,
    MLMessageRequest,
    MLMessageResponse,
)
from .thread_requests import (
    ThreadCreate,
    ThreadUpdate,
    PhoneThreadRequest,
    PhoneThreadResponse,
    ThreadMoveRequest,
    ThreadMoveResponse,
)
from .thread_responses import (
    ThreadResponse,
    ThreadList,
    ThreadSummary,
)

__all__ = [
    "UserBean",
    "AttachmentReference",
    "AttachmentDetails",
    "Citation",
    "MessageCreate",
    "MessageUpdate",
    "MessageDelete",
    "HideThreadMessagesBody",
    "HideThreadMessagesResponse",
    "MessageResponse",
    "MessageList",
    "MLMessageRequest",
    "MLMessageResponse",
    "ThreadCreate",
    "ThreadUpdate",
    "PhoneThreadRequest",
    "PhoneThreadResponse",
    "ThreadMoveRequest",
    "ThreadMoveResponse",
    "ThreadResponse",
    "ThreadList",
    "ThreadSummary",
]
