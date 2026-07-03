"""
Socket-related constants and configuration values
"""

from enum import IntEnum
from typing import List

class SocketEventType(IntEnum):
    """Socket event types for communication"""
    CONNECT = 1
    DISCONNECT = 2
    MESSAGE = 3
    ERROR = 4
    HEARTBEAT = 5
    SHAY_REALTIME = 6  # Custom event for backend communication
    RECONNECT = 7
    CONNECTION_ERROR = 8
    THREAD_CREATED = 8  # Thread creation event
    MESSAGE_CREATED = 11  # Message creation event
    ML_API_RESPONSE = 16  # ML API response event for datasource processing

class SocketConnectionState(IntEnum):
    """Socket connection states"""
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    RECONNECTING = 3
    ERROR = 4

class SocketConfigDefaults:
    """Default configuration values for socket connections"""
    
    # Connection settings
    TIMEOUT: int = 10000  # 10 seconds
    RECONNECTION: bool = True
    RECONNECTION_ATTEMPTS: int = 10
    RECONNECTION_DELAY: int = 1000  # 1 second
    RECONNECTION_DELAY_MAX: int = 5000  # 5 seconds
    AUTO_CONNECT: bool = True
    
    # Transport settings
    # Note: TRANSPORTS removed - not supported in python-socketio v5.x
    # Frontend uses Socket.IO v4.8.1 which supports transports parameter
    
    # Environment-specific settings
    PRODUCTION_PATH: str = '/socket.io/'
    DEVELOPMENT_PATH: str = '/socket.io/'
    
    # Heartbeat settings
    HEARTBEAT_INTERVAL: int = 30000  # 30 seconds
    HEARTBEAT_TIMEOUT: int = 60000  # 60 seconds
    
    # Retry settings
    MAX_RETRY_ATTEMPTS: int = 3
    RETRY_DELAY: int = 1000  # 1 second
    EXPONENTIAL_BACKOFF_BASE: int = 2
    MAX_RETRY_DELAY: int = 30000  # 30 seconds

class SocketErrorCodes(IntEnum):
    """Socket error codes"""
    CONNECTION_FAILED = 1001
    AUTHENTICATION_FAILED = 1002
    TIMEOUT = 1003
    NETWORK_ERROR = 1004
    SERVER_ERROR = 1005
    INVALID_EVENT = 1006
    RATE_LIMITED = 1007
    UNKNOWN_ERROR = 9999

# Event names for socket communication
SOCKET_EVENTS = {
    'CONNECT': 'connect',
    'DISCONNECT': 'disconnect',
    'MESSAGE': 'message',
    'ERROR': 'error',
    'HEARTBEAT': 'heartbeat',
    'SHAY_REALTIME': 'shay_realtime',
    'RECONNECT': 'reconnect',
    'CONNECTION_ERROR': 'connect_error'
}

# Default socket server URLs for different environments
DEFAULT_SOCKET_URLS = {
    'development': 'http://localhost:3000',
    'staging': 'https://staging-socket.shay-ai.com',
    'production': 'https://socket.shay-ai.com'
}

