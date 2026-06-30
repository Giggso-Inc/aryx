"""
Socket integration for FastAPI application
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from app.core.config import settings
from app.services.socket_client_service import get_socket_service
from app.services.socket_event_handler import initialize_socket_event_handler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def socket_lifespan():
    """Socket service lifespan management"""
    socket_service = get_socket_service()
    event_handler = None
    
    try:
        # Initialize socket service if auto-connect is enabled
        if settings.SOCKET_AUTO_CONNECT:
            logger.info("Initializing socket service...")
            
            # Connect to socket server
            socket_client = await socket_service.connect()
            if socket_client:
                logger.info("Socket service connected successfully")
                
                # Initialize event handler
                event_handler = await initialize_socket_event_handler(socket_service)
                logger.info("Socket event handler initialized")
            else:
                logger.warning("Failed to connect to socket server")
        else:
            logger.info("Socket auto-connect disabled")
        
        yield socket_service, event_handler
        
    except Exception as e:
        logger.error(f"Error during socket initialization: {e}")
        yield None, None
    
    finally:
        # Cleanup socket service
        try:
            if socket_service and socket_service.is_socket_connected():
                logger.info("Disconnecting socket service...")
                await socket_service.disconnect()
                logger.info("Socket service disconnected")
            
            if event_handler:
                await event_handler.cleanup()
                logger.info("Socket event handler cleaned up")
                
        except Exception as e:
            logger.error(f"Error during socket cleanup: {e}")


async def initialize_socket_service() -> tuple[Optional[object], Optional[object]]:
    """
    Initialize socket service and event handler
    
    Returns:
        Tuple of (socket_service, event_handler)
    """
    try:
        socket_service = get_socket_service()
        event_handler = None
        
        # Always initialize event handler for queuing events
        event_handler = await initialize_socket_event_handler(socket_service)
        logger.info("Socket event handler initialized")
        
        if settings.SOCKET_AUTO_CONNECT:
            # Connect to socket server
            socket_client = await socket_service.connect()
            if socket_client:
                logger.info("Socket service connected successfully")
            else:
                logger.warning("Failed to connect to socket server")
        
        return socket_service, event_handler
        
    except Exception as e:
        logger.error(f"Failed to initialize socket service: {e}")
        return None, None


async def cleanup_socket_service(socket_service: Optional[object], event_handler: Optional[object]) -> None:
    """
    Cleanup socket service and event handler
    
    Args:
        socket_service: Socket service instance
        event_handler: Event handler instance
    """
    try:
        if socket_service and hasattr(socket_service, 'is_socket_connected'):
            if socket_service.is_socket_connected():
                await socket_service.disconnect()
                logger.info("Socket service disconnected")
        
        if event_handler and hasattr(event_handler, 'cleanup'):
            await event_handler.cleanup()
            logger.info("Socket event handler cleaned up")
            
    except Exception as e:
        logger.error(f"Error during socket cleanup: {e}")


def get_socket_health_status() -> dict:
    """
    Get socket service health status
    
    Returns:
        Dictionary with socket health information
    """
    try:
        socket_service = get_socket_service()
        if not socket_service:
            return {
                "status": "unavailable",
                "connected": False,
                "error": "Socket service not initialized"
            }
        
        connection_status = socket_service.get_connection_status()
        
        return {
            "status": "healthy" if connection_status.connected else "disconnected",
            "connected": connection_status.connected,
            "socket_id": connection_status.socket_id,
            "connection_attempts": connection_status.connection_attempts,
            "last_error": connection_status.last_error,
            "last_heartbeat": connection_status.last_heartbeat.isoformat() if connection_status.last_heartbeat else None
        }
        
    except Exception as e:
        return {
            "status": "error",
            "connected": False,
            "error": str(e)
        }

