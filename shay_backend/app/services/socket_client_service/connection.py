"""
Connection-management mixin for SocketClientService.

Split out of the former app/services/socket_client_service.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a): this mixin owns
connect/disconnect lifecycle and connection-state queries. It is combined
with EventEmissionMixin and InternalHandlersMixin by the SocketClientService
class in client.py — every method here assumes the attributes set up in
SocketClientService.__init__ (self.socket, self._lock, self._settings, etc.)
are already present on `self`.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

import socketio

from app.core.socket_constants import SocketConnectionState
from app.schemas.socket_events import ConnectionStatus

logger = logging.getLogger(__name__)


class ConnectionMixin:
    """Connection lifecycle: connect, disconnect, and status queries."""

    async def connect(self, server_url: Optional[str] = None) -> Optional[socketio.AsyncClient]:
        """
        Connect to socket server

        Args:
            server_url: Optional server URL override

        Returns:
            SocketIO client instance or None if connection failed
        """
        async with self._lock:
            if self.is_connected and self.socket:
                logger.info("Socket already connected")
                return self.socket

            try:
                self._connection_state = SocketConnectionState.CONNECTING
                self._connection_attempts += 1

                # Use provided URL or default from settings
                url = server_url or self._settings.SOCKET_SERVER_URL

                # Create socket client
                self.socket = socketio.AsyncClient(
                    logger=self._settings.SOCKET_DEBUG,
                    engineio_logger=self._settings.SOCKET_DEBUG,
                )

                # Setup event handlers
                await self._setup_default_handlers()

                # Connection options
                connection_options = {
                    "transports": [t.strip() for t in self._settings.SOCKET_TRANSPORTS.split(",")]
                }

                # Add optional parameters
                if self._settings.SOCKET_NAMESPACE:
                    connection_options["namespace"] = self._settings.SOCKET_NAMESPACE

                if self._settings.SOCKET_AUTH_TOKEN:
                    connection_options["auth"] = {"token": self._settings.SOCKET_AUTH_TOKEN}

                # Note: headers and query_params not available in main config

                # Connect to server
                logger.info(f"Connecting to socket server: {url}")
                await self.socket.connect(url, **connection_options)

                # Wait for connection to be established
                await asyncio.sleep(0.1)  # Small delay to ensure connection is established

                if self.socket.connected:
                    self.is_connected = True
                    self._connection_state = SocketConnectionState.CONNECTED
                    self._socket_id = self.socket.sid
                    self._connection_attempts = 0
                    self._last_error = None

                    # Start heartbeat if enabled
                    if self._settings.SOCKET_HEARTBEAT_INTERVAL > 0:
                        await self._start_heartbeat()

                    logger.info(f"Successfully connected to socket server. Socket ID: {self._socket_id}")
                    return self.socket
                else:
                    raise Exception("Connection failed - socket not connected after connect call")

            except Exception as e:
                self._connection_state = SocketConnectionState.ERROR
                self._last_error = str(e)
                self.is_connected = False
                logger.error(f"Failed to connect to socket server: {e}")

                # Cleanup on failure
                if self.socket:
                    await self.socket.disconnect()
                    self.socket = None

                return None

    async def disconnect(self) -> None:
        """Disconnect from socket server"""
        async with self._lock:
            if not self.is_connected or not self.socket:
                logger.info("Socket not connected, nothing to disconnect")
                return

            try:
                # Stop heartbeat
                await self._stop_heartbeat()

                # Disconnect socket
                await self.socket.disconnect()

                self.is_connected = False
                self._connection_state = SocketConnectionState.DISCONNECTED
                self._socket_id = None

                logger.info("Disconnected from socket server")

            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
            finally:
                self.socket = None

    async def force_connect(self, server_url: Optional[str] = None) -> Optional[socketio.AsyncClient]:
        """
        Force connection by disconnecting first if connected

        Args:
            server_url: Optional server URL override

        Returns:
            SocketIO client instance or None if connection failed
        """
        if self.is_connected:
            await self.disconnect()

        return await self.connect(server_url)

    async def ensure_connection(self) -> bool:
        """
        Ensure socket is connected, attempt reconnection if needed

        Returns:
            True if connected, False otherwise
        """
        if self.is_connected and self.socket and self.socket.connected:
            return True

        if not self.is_connected:
            result = await self.connect()
            return result is not None

        return False

    def get_socket(self) -> Optional[socketio.AsyncClient]:
        """Get current socket instance"""
        return self.socket

    def is_socket_connected(self) -> bool:
        """Check if socket is connected"""
        return self.is_connected and self.socket is not None and self.socket.connected

    def get_connection_status(self) -> ConnectionStatus:
        """Get detailed connection status"""
        return ConnectionStatus(
            connected=self.is_connected,
            socket_id=self._socket_id,
            has_socket=self.socket is not None,
            state=self._connection_state.value,
            last_heartbeat=self._last_heartbeat,
            connection_attempts=self._connection_attempts,
            last_error=self._last_error,
        )

    async def wait_for_connection(self, timeout: int = 5000) -> bool:
        """
        Wait for connection to be established

        Args:
            timeout: Timeout in milliseconds

        Returns:
            True if connected within timeout, False otherwise
        """
        start_time = datetime.utcnow()
        timeout_seconds = timeout / 1000

        while (datetime.utcnow() - start_time).total_seconds() < timeout_seconds:
            if self.is_socket_connected():
                return True
            await asyncio.sleep(0.1)

        return False
