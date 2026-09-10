"""
Socket Client Service - Main implementation for WebSocket client functionality

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a): this used to be a
single 547-line app/services/socket_client_service.py. It is now a package
of submodules by responsibility:
  - connection.py:        ConnectionMixin (connect/disconnect/status)
  - events.py:             EventEmissionMixin (on/off/emit/send_*)
  - internal_handlers.py:  InternalHandlersMixin (_on_*, heartbeat, retry)
  - client.py:             SocketClientService (combines the three mixins,
                            preserves the Singleton __new__/__init__ and the
                            `__new__(cls) -> "SocketClientService"` type hint),
                            plus the module-level `socket_service` instance
                            and `get_socket_service()` accessor.

All names below are re-exported so `from app.services.socket_client_service
import get_socket_service` (used by app/core/socket.py and several route
modules) and `from app.services.socket_client_service import
SocketClientService` (used by app/services/socket_event_handler.py as a type
annotation) need zero changes.
"""

from .client import SocketClientService, get_socket_service, socket_service

__all__ = ["SocketClientService", "socket_service", "get_socket_service"]
