"""
Message routes for thread and message management with AI integration

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5): this used to be a
single 2,513-line app/routes/messages.py. It is now a package of submodules
by resource/sub-area, combined into one `router` below so that
`from app.routes.messages import router` (used by the app's route
registration) needs zero changes.

Route registration ORDER matters here: FastAPI/Starlette matches routes in
registration order for a given HTTP method, and GET /{thread_id}
(messages_read.get_thread_messages) is a single-segment dynamic path that
would otherwise swallow the literal GET /threads path. threads_list (which
owns GET /threads) is therefore included BEFORE messages_read, preserving
the original file's endpoint declaration order exactly.
"""

from fastapi import APIRouter

from . import threads_create
from . import threads_list
from . import messages_create
from . import messages_read
from . import messages_hide
from . import messages_update
from . import messages_delete
from . import threads_manage
from . import threads_move
from . import threads_delete
from . import ml_store
from .socket_events import emit_message_created_event, emit_thread_created_event
from .mentions import (
    parse_mentions_from_content,
    get_users_by_mentions,
    should_send_mention_notification,
    send_mention_notification_email,
    process_mention_notifications,
)
from .system_user import get_or_create_system_user
from .ai_processing import trigger_ai_processing

router = APIRouter()
router.include_router(threads_create.router)
router.include_router(threads_list.router)
router.include_router(messages_create.router)
router.include_router(messages_read.router)
router.include_router(messages_hide.router)
router.include_router(messages_update.router)
router.include_router(messages_delete.router)
router.include_router(threads_manage.router)
router.include_router(threads_move.router)
router.include_router(threads_delete.router)
router.include_router(ml_store.router)

__all__ = [
    "router",
    "emit_message_created_event",
    "emit_thread_created_event",
    "parse_mentions_from_content",
    "get_users_by_mentions",
    "should_send_mention_notification",
    "send_mention_notification_email",
    "process_mention_notifications",
    "get_or_create_system_user",
    "trigger_ai_processing",
]
