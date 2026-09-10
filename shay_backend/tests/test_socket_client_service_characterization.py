"""
Golden-master / characterization tests for app/services/socket_client_service.py.

Purpose: socket_client_service.py is 547 lines with ZERO existing test
coverage. It is about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a). Before the split,
we capture the CURRENT observable behavior of the Singleton
`SocketClientService` and `get_socket_service()` so the split can be
verified to change nothing.

`SocketClientService` is a process-wide Singleton (`__new__` always returns
the same instance, `__init__` only runs its body once via `_initialized`).
To get test isolation we forcibly reset `_instance`/`_initialized` around
every test in this file (autouse fixture below) so each test gets a fresh
instance state, matching how the class would behave on a fresh process.

No pytest-asyncio is installed; async methods are driven via
`asyncio.run()`, matching tests/test_channels_characterization.py's pattern.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_singleton():
    from app.services.socket_client_service import SocketClientService

    SocketClientService._instance = None
    SocketClientService._initialized = False
    yield
    SocketClientService._instance = None
    SocketClientService._initialized = False


def _settings_patch(**overrides):
    from app.core.config import settings

    return patch.multiple(settings, **overrides)


# ---------------------------------------------------------------------------
# Singleton behavior
# ---------------------------------------------------------------------------
def test_singleton_returns_same_instance():
    from app.services.socket_client_service import SocketClientService

    a = SocketClientService()
    b = SocketClientService()
    assert a is b


def test_init_sets_expected_defaults():
    from app.core.socket_constants import SocketConnectionState
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    assert svc.socket is None
    assert svc.is_connected is False
    assert svc._connection_state == SocketConnectionState.DISCONNECTED
    assert svc._connection_attempts == 0
    assert svc._last_error is None
    assert svc._event_handlers == {}


def test_get_socket_service_returns_module_singleton():
    from app.services.socket_client_service import get_socket_service, socket_service

    assert get_socket_service() is socket_service


# ---------------------------------------------------------------------------
# connect / disconnect / force_connect / ensure_connection
# ---------------------------------------------------------------------------
def _mock_async_client(connected=True, sid="sid-123"):
    mock_socket = MagicMock()
    mock_socket.connected = connected
    mock_socket.sid = sid
    mock_socket.connect = AsyncMock()
    mock_socket.disconnect = AsyncMock()
    mock_socket.on = MagicMock()
    mock_socket.off = MagicMock()
    mock_socket.emit = AsyncMock()
    return mock_socket


def test_connect_success_sets_connected_state():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    mock_socket = _mock_async_client(connected=True, sid="sid-abc")

    with _settings_patch(
        SOCKET_SERVER_URL="ws://test",
        SOCKET_DEBUG=False,
        SOCKET_TRANSPORTS="websocket,polling",
        SOCKET_NAMESPACE=None,
        SOCKET_AUTH_TOKEN=None,
        SOCKET_HEARTBEAT_INTERVAL=0,
    ), patch("app.services.socket_client_service.connection.socketio.AsyncClient", return_value=mock_socket):
        result = asyncio.run(svc.connect())

    assert result is mock_socket
    assert svc.is_connected is True
    assert svc._socket_id == "sid-abc"
    mock_socket.connect.assert_awaited_once()


def test_connect_already_connected_returns_existing_socket_without_reconnecting():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    existing_socket = _mock_async_client(connected=True)
    svc.socket = existing_socket
    svc.is_connected = True

    result = asyncio.run(svc.connect())
    assert result is existing_socket
    existing_socket.connect.assert_not_called()


def test_connect_failure_returns_none_and_cleans_up():
    from app.core.socket_constants import SocketConnectionState
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    mock_socket = _mock_async_client(connected=True)
    mock_socket.connect = AsyncMock(side_effect=RuntimeError("boom"))

    with _settings_patch(
        SOCKET_SERVER_URL="ws://test",
        SOCKET_DEBUG=False,
        SOCKET_TRANSPORTS="websocket",
        SOCKET_NAMESPACE=None,
        SOCKET_AUTH_TOKEN=None,
    ), patch("app.services.socket_client_service.connection.socketio.AsyncClient", return_value=mock_socket):
        result = asyncio.run(svc.connect())

    assert result is None
    assert svc.is_connected is False
    assert svc._connection_state == SocketConnectionState.ERROR
    assert svc._last_error == "boom"
    assert svc.socket is None


def test_connect_not_connected_after_call_raises_and_returns_none():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    mock_socket = _mock_async_client(connected=False)

    with _settings_patch(
        SOCKET_SERVER_URL="ws://test",
        SOCKET_DEBUG=False,
        SOCKET_TRANSPORTS="websocket",
        SOCKET_NAMESPACE=None,
        SOCKET_AUTH_TOKEN=None,
    ), patch("app.services.socket_client_service.connection.socketio.AsyncClient", return_value=mock_socket):
        result = asyncio.run(svc.connect())

    assert result is None
    assert svc.is_connected is False


def test_disconnect_when_not_connected_is_noop():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    asyncio.run(svc.disconnect())  # should not raise
    assert svc.socket is None
    assert svc.is_connected is False


def test_disconnect_success_path():
    from app.core.socket_constants import SocketConnectionState
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    mock_socket = _mock_async_client(connected=True)
    svc.socket = mock_socket
    svc.is_connected = True
    svc._socket_id = "sid-1"

    asyncio.run(svc.disconnect())

    mock_socket.disconnect.assert_awaited_once()
    assert svc.is_connected is False
    assert svc._connection_state == SocketConnectionState.DISCONNECTED
    assert svc._socket_id is None
    assert svc.socket is None


def test_force_connect_disconnects_first_when_connected():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    mock_socket = _mock_async_client(connected=True)
    svc.socket = mock_socket
    svc.is_connected = True

    new_socket = _mock_async_client(connected=True, sid="new-sid")
    with _settings_patch(
        SOCKET_SERVER_URL="ws://test",
        SOCKET_DEBUG=False,
        SOCKET_TRANSPORTS="websocket",
        SOCKET_NAMESPACE=None,
        SOCKET_AUTH_TOKEN=None,
        SOCKET_HEARTBEAT_INTERVAL=0,
    ), patch("app.services.socket_client_service.connection.socketio.AsyncClient", return_value=new_socket):
        result = asyncio.run(svc.force_connect())

    mock_socket.disconnect.assert_awaited_once()
    assert result is new_socket


def test_ensure_connection_already_connected_returns_true():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.socket = _mock_async_client(connected=True)
    svc.is_connected = True

    assert asyncio.run(svc.ensure_connection()) is True


def test_ensure_connection_not_connected_attempts_connect():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    mock_socket = _mock_async_client(connected=True)

    with _settings_patch(
        SOCKET_SERVER_URL="ws://test",
        SOCKET_DEBUG=False,
        SOCKET_TRANSPORTS="websocket",
        SOCKET_NAMESPACE=None,
        SOCKET_AUTH_TOKEN=None,
        SOCKET_HEARTBEAT_INTERVAL=0,
    ), patch("app.services.socket_client_service.connection.socketio.AsyncClient", return_value=mock_socket):
        result = asyncio.run(svc.ensure_connection())

    assert result is True


def test_ensure_connection_partial_state_returns_false():
    """Characterizes the unreachable-looking branch: is_connected True but
    socket falsy/not-connected falls through both ifs to `return False`."""
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.is_connected = True
    svc.socket = None

    assert asyncio.run(svc.ensure_connection()) is False


# ---------------------------------------------------------------------------
# get_socket / is_socket_connected / get_connection_status / wait_for_connection
# ---------------------------------------------------------------------------
def test_get_socket_and_is_socket_connected():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    assert svc.get_socket() is None
    assert svc.is_socket_connected() is False

    svc.socket = _mock_async_client(connected=True)
    svc.is_connected = True
    assert svc.get_socket() is svc.socket
    assert svc.is_socket_connected() is True


def test_get_connection_status_reflects_state():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc._socket_id = "sid-x"
    svc._connection_attempts = 2
    svc._last_error = "oops"
    status = svc.get_connection_status()

    assert status.connected is False
    assert status.socket_id == "sid-x"
    assert status.connection_attempts == 2
    assert status.last_error == "oops"


def test_wait_for_connection_times_out_false():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    result = asyncio.run(svc.wait_for_connection(timeout=150))
    assert result is False


def test_wait_for_connection_returns_true_when_connected():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.socket = _mock_async_client(connected=True)
    svc.is_connected = True

    result = asyncio.run(svc.wait_for_connection(timeout=1000))
    assert result is True


# ---------------------------------------------------------------------------
# on / off
# ---------------------------------------------------------------------------
def test_on_registers_handler_locally_and_no_socket():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    cb = MagicMock()
    svc.on("my_event", cb)

    assert svc._event_handlers["my_event"] == [cb]


def test_on_registers_with_live_socket_too():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.socket = _mock_async_client(connected=True)
    cb = MagicMock()
    svc.on("my_event", cb)

    svc.socket.on.assert_called_with("my_event", cb)


def test_off_removes_specific_callback():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    cb1, cb2 = MagicMock(), MagicMock()
    svc.on("evt", cb1)
    svc.on("evt", cb2)

    svc.off("evt", cb1)
    assert svc._event_handlers["evt"] == [cb2]


def test_off_without_callback_clears_all():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.on("evt", MagicMock())
    svc.on("evt", MagicMock())

    svc.off("evt")
    assert svc._event_handlers["evt"] == []


def test_off_unknown_event_is_noop():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.off("never_registered")  # should not raise


# ---------------------------------------------------------------------------
# emit / force_emit
# ---------------------------------------------------------------------------
def test_emit_when_not_connected_logs_warning_and_skips():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    asyncio.run(svc.emit("evt", {"a": 1}))  # should not raise, no socket to call


def test_emit_success_calls_socket_emit():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.socket = _mock_async_client(connected=True)
    svc.is_connected = True

    asyncio.run(svc.emit("evt", {"a": 1}))
    svc.socket.emit.assert_awaited_once_with("evt", {"a": 1})


def test_emit_exception_is_swallowed():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.socket = _mock_async_client(connected=True)
    svc.socket.emit = AsyncMock(side_effect=RuntimeError("emit failed"))
    svc.is_connected = True

    asyncio.run(svc.emit("evt", {}))  # should not raise


def test_force_emit_not_connected_and_reconnect_fails():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    with patch.object(svc, "ensure_connection", AsyncMock(return_value=False)):
        result = asyncio.run(svc.force_emit("evt", {}))
    assert result is False


def test_force_emit_reconnects_then_emits():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()

    async def _fake_ensure_connection():
        svc.socket = _mock_async_client(connected=True)
        svc.is_connected = True
        return True

    with patch.object(svc, "ensure_connection", _fake_ensure_connection):
        result = asyncio.run(svc.force_emit("evt", {"x": 1}))

    assert result is True
    svc.socket.emit.assert_awaited_once_with("evt", {"x": 1})


def test_force_emit_already_connected_emits_directly():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.socket = _mock_async_client(connected=True)
    svc.is_connected = True

    result = asyncio.run(svc.force_emit("evt", {"x": 1}))
    assert result is True
    svc.socket.emit.assert_awaited_once_with("evt", {"x": 1})


# ---------------------------------------------------------------------------
# send_* helper methods
# ---------------------------------------------------------------------------
def test_send_socket_message_success():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.socket = _mock_async_client(connected=True)
    svc.is_connected = True

    result = asyncio.run(
        svc.send_socket_message({"event": "custom", "data": {"k": "v"}, "room": "r1"})
    )
    assert result is True
    svc.socket.emit.assert_awaited_once()
    args, _ = svc.socket.emit.call_args
    assert args[0] == "custom"


def test_send_shay_realtime_event_success():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.socket = _mock_async_client(connected=True)
    svc.is_connected = True

    result = asyncio.run(svc.send_shay_realtime_event("some_type", {"foo": "bar"}))
    assert result is True
    svc.socket.emit.assert_awaited_once()


def test_send_shay_realtime_event_exception_returns_false():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    # Force a validation-style failure by passing a non-serializable kwarg
    # that ShayRealtimeData construction rejects.
    with patch(
        "app.services.socket_client_service.events.ShayRealtimeData",
        side_effect=RuntimeError("bad payload"),
    ):
        result = asyncio.run(svc.send_shay_realtime_event("t", {}))
    assert result is False


def test_send_thread_created_event_success():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.socket = _mock_async_client(connected=True)
    svc.is_connected = True

    result = asyncio.run(svc.send_thread_created_event("chan-1", "thread-1"))
    assert result is True
    args, _ = svc.socket.emit.call_args
    assert args[0] == "shay_realtime"
    assert args[1]["type"] == 8


def test_send_message_created_event_success():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.socket = _mock_async_client(connected=True)
    svc.is_connected = True

    result = asyncio.run(svc.send_message_created_event("chan-1", "thread-1", "msg-1"))
    assert result is True
    args, _ = svc.socket.emit.call_args
    assert args[0] == "shay_realtime"
    assert args[1]["type"] == 11


# ---------------------------------------------------------------------------
# internal handlers
# ---------------------------------------------------------------------------
def test_setup_default_handlers_noop_without_socket():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    asyncio.run(svc._setup_default_handlers())  # no socket set; should just return


def test_setup_default_handlers_registers_with_socket():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.socket = _mock_async_client(connected=True)

    asyncio.run(svc._setup_default_handlers())
    assert svc.socket.on.call_count == 5


def test_on_connect_sets_state():
    from app.core.socket_constants import SocketConnectionState
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.socket = _mock_async_client(connected=True, sid="new-sid")

    asyncio.run(svc._on_connect())
    assert svc.is_connected is True
    assert svc._connection_state == SocketConnectionState.CONNECTED
    assert svc._socket_id == "new-sid"


def test_on_disconnect_sets_state_and_stops_heartbeat():
    from app.core.socket_constants import SocketConnectionState
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.is_connected = True
    svc._socket_id = "sid"

    asyncio.run(svc._on_disconnect())
    assert svc.is_connected is False
    assert svc._connection_state == SocketConnectionState.DISCONNECTED
    assert svc._socket_id is None


def test_on_connect_error_sets_error_state():
    from app.core.socket_constants import SocketConnectionState
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    asyncio.run(svc._on_connect_error("bad handshake"))
    assert svc._connection_state == SocketConnectionState.ERROR
    assert svc._last_error == "bad handshake"
    assert svc.is_connected is False


def test_on_heartbeat_sets_last_heartbeat():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    assert svc._last_heartbeat is None
    asyncio.run(svc._on_heartbeat({"ok": True}))
    assert svc._last_heartbeat is not None


def test_on_error_sets_last_error():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    asyncio.run(svc._on_error("some error"))
    assert svc._last_error == "some error"


def test_start_and_stop_heartbeat_task_lifecycle():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    svc.is_connected = False  # loop body exits immediately since is_connected is False

    asyncio.run(svc._start_heartbeat())
    assert svc._heartbeat_task is not None

    asyncio.run(svc._stop_heartbeat())
    assert svc._heartbeat_task is None


def test_start_heartbeat_is_idempotent_while_running():
    from app.services.socket_client_service import SocketClientService

    async def _run():
        svc = SocketClientService()
        svc.is_connected = True
        svc.socket = _mock_async_client(connected=True)
        await svc._start_heartbeat()
        first_task = svc._heartbeat_task
        await svc._start_heartbeat()  # should not replace a running task
        second_task = svc._heartbeat_task
        await svc._stop_heartbeat()
        return first_task is second_task

    assert asyncio.run(_run()) is True


def test_retry_operation_retries_then_succeeds():
    from app.services.socket_client_service import SocketClientService

    svc = SocketClientService()
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")
        return "ok"

    result = asyncio.run(svc._retry_operation(flaky))
    assert result == "ok"
    assert calls["n"] == 2
