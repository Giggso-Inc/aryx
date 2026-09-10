"""
Socket Event Handler - Manages socket events and provides event processing capabilities

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a): this used to be a
single 490-line app/services/socket_event_handler.py. It is now a package of
submodules by responsibility:
  - callbacks.py:  SocketCallbacksMixin (handle_connect/disconnect/heartbeat/
                   error/shay_realtime/message, and their socket.io wiring)
  - processing.py: ProcessingMixin (processor/middleware registration,
                   _emit_event dispatch)
  - queue.py:      QueueMixin (background queue-processor task, the
                   default/connection/authentication/timeout error
                   handlers, cleanup)
  - handler.py:    SocketEventHandler (combines the three mixins,
                   __init__, setup_event_handlers)

The module-level singleton (`socket_event_handler` global +
`get_socket_event_handler`/`initialize_socket_event_handler`) is kept HERE
in __init__.py rather than in its own submodule: the original flat file's
`global socket_event_handler` statement inside `initialize_socket_event_handler`
binds to that file's own module namespace, and since this package's
__init__.py IS `app.services.socket_event_handler`'s module namespace (same
dotted path as before), keeping the singleton here preserves that binding
exactly — moving it to a child submodule would split the global variable
from the functions that mutate it via two different module objects.
"""

from typing import Optional

from app.services.socket_client_service import SocketClientService

from .handler import SocketEventHandler

__all__ = [
    "SocketEventHandler",
    "get_socket_event_handler",
    "initialize_socket_event_handler",
]

# Global event handler instance
socket_event_handler: Optional[SocketEventHandler] = None


def get_socket_event_handler() -> Optional[SocketEventHandler]:
    """Get global socket event handler instance"""
    return socket_event_handler


async def initialize_socket_event_handler(socket_service: SocketClientService) -> SocketEventHandler:
    """Initialize socket event handler"""
    global socket_event_handler

    if socket_event_handler is None:
        socket_event_handler = SocketEventHandler(socket_service)
        await socket_event_handler.setup_event_handlers()

    return socket_event_handler
