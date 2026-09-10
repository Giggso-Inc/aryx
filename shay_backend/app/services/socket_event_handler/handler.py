"""
SocketEventHandler - assembles the callback, processing, and queue mixins.

Split out of the former app/services/socket_event_handler.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a).

Stated exception: SocketEventHandler remains ONE class (composed from three
mixins) rather than three independent collaborator objects, because its
methods share mutable per-instance state (`_event_processors`,
`_middleware`, `_error_handlers`, `_event_queue`, `_queue_processor_task`)
that callback, processing, and queue-management methods all read and write
interchangeably (e.g. a callback's `_emit_event` call feeds into the
processing mixin's middleware pipeline, which is itself invoked by the
queue mixin's background loop). Splitting further would mean threading that
shared state through explicit collaborator objects for no behavioral gain.
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from app.services.socket_client_service import SocketClientService

from .callbacks import SocketCallbacksMixin
from .processing import ProcessingMixin
from .queue import QueueMixin

logger = logging.getLogger(__name__)


class SocketEventHandler(SocketCallbacksMixin, ProcessingMixin, QueueMixin):
    """
    Handles socket events and provides event processing capabilities
    """

    def __init__(self, socket_service: SocketClientService):
        self.socket_service = socket_service
        self._event_processors: Dict[str, List[Callable]] = {}
        self._middleware: List[Callable] = []
        self._error_handlers: Dict[str, Callable] = {}
        self._event_queue: List[Dict[str, Any]] = []
        self._queue_processor_task: Optional[asyncio.Task] = None
        self._is_processing = False

    async def setup_event_handlers(self) -> None:
        """Setup all event handlers"""
        try:
            # Setup core event handlers
            await self._setup_connection_handlers()
            await self._setup_custom_handlers()
            await self._setup_error_handlers()

            # Start event queue processor
            await self._start_queue_processor()

            logger.info("Socket event handlers setup completed")

        except Exception as e:
            logger.error(f"Failed to setup event handlers: {e}")
            raise
