"""
Socket Client Service - Singleton assembling the connection, event, and
internal-handler mixins into the public SocketClientService class.

Split out of the former app/services/socket_client_service.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a).

Stated exception: SocketClientService remains ONE class (composed from three
mixins) rather than three independent classes, because it is a process-wide
Singleton holding shared mutable connection state (self.socket, self._lock,
counters, etc.) that every method across connection/event/handler
responsibilities reads and writes — splitting it into separate objects would
require passing that shared state around explicitly and would change the
`__new__`/`_initialized` singleton contract relied on by every caller of
`get_socket_service()`.
"""

import asyncio
import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional

import socketio

from app.core.config import settings
from app.core.socket_constants import SocketConnectionState

from .connection import ConnectionMixin
from .events import EventEmissionMixin
from .internal_handlers import InternalHandlersMixin

logger = logging.getLogger(__name__)


class SocketClientService(ConnectionMixin, EventEmissionMixin, InternalHandlersMixin):
    """
    Singleton Socket Client Service for managing WebSocket connections
    Provides connection management, event handling, and real-time communication
    """

    _instance = None
    _initialized = False

    def __new__(cls) -> "SocketClientService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.socket: Optional[socketio.AsyncClient] = None
            self.is_connected: bool = False
            self.connection_promise: Optional[asyncio.Future] = None
            self._lock = asyncio.Lock()
            self._event_handlers: Dict[str, List[Callable]] = {}
            self._connection_state = SocketConnectionState.DISCONNECTED
            self._connection_attempts = 0
            self._last_error: Optional[str] = None
            self._last_heartbeat: Optional[datetime] = None
            self._socket_id: Optional[str] = None
            # Use main config settings directly
            self._settings = settings
            self._heartbeat_task: Optional[asyncio.Task] = None
            self._reconnect_task: Optional[asyncio.Task] = None
            self._initialized = True
            logger.info("SocketClientService initialized")


# Global socket service instance
socket_service = SocketClientService()


def get_socket_service() -> SocketClientService:
    """Get global socket service instance"""
    return socket_service
