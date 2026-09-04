"""
Golden-master / characterization tests for app/services/socket_event_handler.py.

Purpose: socket_event_handler.py is 490 lines with ZERO existing test
coverage. It is about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a). Before the split,
we capture the CURRENT observable behavior of `SocketEventHandler` and the
module-level `get_socket_event_handler`/`initialize_socket_event_handler`
singleton accessors so the split can be verified to change nothing.

`initialize_socket_event_handler` uses a module-level global
(`socket_event_handler`) as a lazy singleton; tests that touch it reset that
global via monkeypatching the module attribute directly (there is no public
reset API).

No pytest-asyncio is installed; async methods are driven via
`asyncio.run()`, matching tests/test_channels_characterization.py's pattern.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_handler():
    from app.services.socket_event_handler import SocketEventHandler

    mock_socket_service = MagicMock()
    mock_socket_service.on = MagicMock()
    mock_socket_service.emit = AsyncMock()
    mock_socket_service.send_shay_realtime_event = AsyncMock()
    mock_socket_service.ensure_connection = AsyncMock(return_value=True)
    mock_socket_service._socket_id = "sid-1"
    mock_socket_service._last_heartbeat = None
    handler = SocketEventHandler(mock_socket_service)
    return handler, mock_socket_service


# ---------------------------------------------------------------------------
# __init__ / setup_event_handlers
# ---------------------------------------------------------------------------
def test_init_sets_expected_defaults():
    handler, mock_socket_service = _make_handler()
    assert handler.socket_service is mock_socket_service
    assert handler._event_processors == {}
    assert handler._middleware == []
    assert handler._error_handlers == {}
    assert handler._event_queue == []
    assert handler._is_processing is False


def test_setup_event_handlers_registers_all_and_starts_queue():
    handler, mock_socket_service = _make_handler()
    asyncio.run(handler.setup_event_handlers())

    registered_events = [call.args[0] for call in mock_socket_service.on.call_args_list]
    assert "connect" in registered_events
    assert "disconnect" in registered_events
    assert "connect_error" in registered_events
    assert "reconnect" in registered_events

    assert set(handler._error_handlers.keys()) == {
        "default",
        "connection",
        "authentication",
        "timeout",
    }
    assert handler._queue_processor_task is not None
    asyncio.run(handler._stop_queue_processor())


# ---------------------------------------------------------------------------
# handle_* callbacks
# ---------------------------------------------------------------------------
def test_handle_connect_processes_queue_and_emits():
    handler, mock_socket_service = _make_handler()
    handler.queue_event("emit", {"event": "foo", "payload": {"a": 1}})

    asyncio.run(handler.handle_connect())

    mock_socket_service.emit.assert_awaited_once_with("foo", {"a": 1})
    assert handler._event_queue == []


def test_handle_disconnect_does_not_raise():
    handler, _ = _make_handler()
    asyncio.run(handler.handle_disconnect())


def test_handle_connect_error_builds_socket_error():
    handler, _ = _make_handler()
    asyncio.run(handler.handle_connect_error(RuntimeError("bad handshake")))  # should not raise


def test_handle_connect_error_with_none_error_uses_default_message():
    handler, _ = _make_handler()
    asyncio.run(handler.handle_connect_error(None))  # should not raise


def test_handle_reconnect_does_not_raise():
    handler, _ = _make_handler()
    asyncio.run(handler.handle_reconnect())


def test_handle_heartbeat_updates_last_heartbeat_dict_payload():
    handler, mock_socket_service = _make_handler()
    asyncio.run(handler.handle_heartbeat({"client_id": "c1"}))
    assert mock_socket_service._last_heartbeat is not None


def test_handle_heartbeat_non_dict_payload_uses_default_construction():
    handler, mock_socket_service = _make_handler()
    asyncio.run(handler.handle_heartbeat("not-a-dict"))  # should not raise
    assert mock_socket_service._last_heartbeat is not None


def test_handle_error_builds_socket_error():
    handler, _ = _make_handler()
    asyncio.run(handler.handle_error("boom"))  # should not raise


def test_handle_shay_realtime_dict_payload():
    handler, _ = _make_handler()
    asyncio.run(handler.handle_shay_realtime({"event_type": "t1", "payload": {"x": 1}}))


def test_handle_shay_realtime_non_dict_payload_uses_unknown_type():
    handler, _ = _make_handler()
    asyncio.run(handler.handle_shay_realtime("raw string"))  # should not raise


def test_handle_message_emits_event():
    handler, _ = _make_handler()
    asyncio.run(handler.handle_message({"body": "hi"}))  # should not raise


# ---------------------------------------------------------------------------
# processor / middleware / error-handler registration
# ---------------------------------------------------------------------------
def test_register_and_unregister_event_processor():
    handler, _ = _make_handler()
    proc1, proc2 = MagicMock(), MagicMock()

    handler.register_event_processor("custom", proc1)
    handler.register_event_processor("custom", proc2)
    assert handler._event_processors["custom"] == [proc1, proc2]

    handler.unregister_event_processor("custom", proc1)
    assert handler._event_processors["custom"] == [proc2]

    handler.unregister_event_processor("custom")
    assert handler._event_processors["custom"] == []


def test_unregister_event_processor_unknown_type_is_noop():
    handler, _ = _make_handler()
    handler.unregister_event_processor("never_registered")  # should not raise


def test_add_and_remove_middleware():
    handler, _ = _make_handler()
    mw = MagicMock()
    handler.add_middleware(mw)
    assert handler._middleware == [mw]

    handler.remove_middleware(mw)
    assert handler._middleware == []


def test_remove_middleware_not_present_is_noop():
    handler, _ = _make_handler()
    handler.remove_middleware(MagicMock())  # should not raise


def test_register_error_handler_overwrites():
    handler, _ = _make_handler()
    h1, h2 = MagicMock(), MagicMock()
    handler.register_error_handler("custom_type", h1)
    handler.register_error_handler("custom_type", h2)
    assert handler._error_handlers["custom_type"] is h2


# ---------------------------------------------------------------------------
# _emit_event / middleware pipeline / processors
# ---------------------------------------------------------------------------
def test_emit_event_runs_middleware_and_processors():
    from app.core.socket_constants import SocketEventType

    handler, _ = _make_handler()
    seen = {}

    async def mw(event_data):
        event_data.source = "middleware-touched"
        return event_data

    async def processor(event_data):
        seen["data"] = event_data

    handler.add_middleware(mw)
    handler.register_event_processor(SocketEventType.MESSAGE.name.lower(), processor)

    asyncio.run(handler._emit_event(SocketEventType.MESSAGE, {"k": "v"}))

    assert seen["data"].source == "middleware-touched"
    assert seen["data"].data == {"k": "v"}


def test_emit_event_middleware_exception_is_non_fatal():
    from app.core.socket_constants import SocketEventType

    handler, _ = _make_handler()

    async def bad_mw(event_data):
        raise RuntimeError("mw failed")

    handler.add_middleware(bad_mw)
    asyncio.run(handler._emit_event(SocketEventType.MESSAGE, {}))  # should not raise


def test_process_with_processors_exception_is_non_fatal():
    from app.core.socket_constants import SocketEventType

    handler, _ = _make_handler()

    async def bad_processor(event_data):
        raise RuntimeError("processor failed")

    handler.register_event_processor(SocketEventType.MESSAGE.name.lower(), bad_processor)
    asyncio.run(handler._emit_event(SocketEventType.MESSAGE, {}))  # should not raise


# ---------------------------------------------------------------------------
# queue processing
# ---------------------------------------------------------------------------
def test_queue_event_appends_with_timestamp():
    handler, _ = _make_handler()
    handler.queue_event("emit", {"event": "foo", "payload": {}})
    assert len(handler._event_queue) == 1
    assert handler._event_queue[0]["type"] == "emit"
    assert "timestamp" in handler._event_queue[0]


def test_process_queued_events_emit_type():
    handler, mock_socket_service = _make_handler()
    handler.queue_event("emit", {"event": "e1", "payload": {"p": 1}})

    asyncio.run(handler._process_queued_events())

    mock_socket_service.emit.assert_awaited_once_with("e1", {"p": 1})
    assert handler._event_queue == []


def test_process_queued_events_shay_realtime_type():
    handler, mock_socket_service = _make_handler()
    handler.queue_event(
        "shay_realtime",
        {"event_type": "t1", "payload": {"p": 1}, "kwargs": {"user_id": "u1"}},
    )

    asyncio.run(handler._process_queued_events())

    mock_socket_service.send_shay_realtime_event.assert_awaited_once_with(
        "t1", {"p": 1}, user_id="u1"
    )


def test_process_event_unknown_type_is_noop():
    handler, mock_socket_service = _make_handler()
    asyncio.run(handler._process_event({"type": "unknown", "data": {}}))
    mock_socket_service.emit.assert_not_awaited()


def test_process_queued_events_exception_is_non_fatal_and_continues():
    handler, mock_socket_service = _make_handler()
    # First event will raise (data is None so .get fails), second should still process.
    handler._event_queue = [
        {"type": "emit", "data": None},
        {"type": "emit", "data": {"event": "e2", "payload": {}}},
    ]

    asyncio.run(handler._process_queued_events())
    mock_socket_service.emit.assert_awaited_once_with("e2", {})


# ---------------------------------------------------------------------------
# error handlers
# ---------------------------------------------------------------------------
def test_default_error_handler_does_not_raise():
    from app.schemas.socket_events import SocketError
    from datetime import datetime

    handler, _ = _make_handler()
    err = SocketError(code=9999, message="oops", timestamp=datetime.utcnow())
    asyncio.run(handler._default_error_handler(err))


def test_connection_error_handler_calls_ensure_connection():
    from app.schemas.socket_events import SocketError
    from datetime import datetime

    handler, mock_socket_service = _make_handler()
    err = SocketError(code=1001, message="conn lost", timestamp=datetime.utcnow())
    asyncio.run(handler._connection_error_handler(err))
    mock_socket_service.ensure_connection.assert_awaited_once()


def test_authentication_and_timeout_error_handlers_do_not_raise():
    from app.schemas.socket_events import SocketError
    from datetime import datetime

    handler, _ = _make_handler()
    err = SocketError(code=9999, message="x", timestamp=datetime.utcnow())
    asyncio.run(handler._authentication_error_handler(err))
    asyncio.run(handler._timeout_error_handler(err))


# ---------------------------------------------------------------------------
# queue processor task lifecycle
# ---------------------------------------------------------------------------
def test_start_queue_processor_idempotent():
    async def _run():
        handler, _ = _make_handler()
        await handler._start_queue_processor()
        first = handler._queue_processor_task
        await handler._start_queue_processor()  # should not replace running task
        second = handler._queue_processor_task
        await handler._stop_queue_processor()
        return first is second

    assert asyncio.run(_run()) is True


def test_stop_queue_processor_when_not_running_is_noop():
    handler, _ = _make_handler()
    asyncio.run(handler._stop_queue_processor())  # should not raise
    assert handler._queue_processor_task is None


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------
def test_cleanup_clears_all_state():
    handler, _ = _make_handler()
    handler.register_event_processor("a", MagicMock())
    handler.add_middleware(MagicMock())
    handler.register_error_handler("b", MagicMock())
    handler.queue_event("emit", {"event": "e", "payload": {}})
    asyncio.run(handler._start_queue_processor())

    asyncio.run(handler.cleanup())

    assert handler._event_processors == {}
    assert handler._middleware == []
    assert handler._error_handlers == {}
    assert handler._event_queue == []
    assert handler._queue_processor_task is None


# ---------------------------------------------------------------------------
# module-level singleton: get_socket_event_handler / initialize_socket_event_handler
# ---------------------------------------------------------------------------
def test_get_socket_event_handler_defaults_to_none():
    import app.services.socket_event_handler as module

    original = module.socket_event_handler
    module.socket_event_handler = None
    try:
        assert module.get_socket_event_handler() is None
    finally:
        module.socket_event_handler = original


def test_initialize_socket_event_handler_creates_once_and_reuses():
    import app.services.socket_event_handler as module

    original = module.socket_event_handler
    module.socket_event_handler = None
    try:
        mock_socket_service = MagicMock()
        mock_socket_service.on = MagicMock()

        first = asyncio.run(module.initialize_socket_event_handler(mock_socket_service))
        second = asyncio.run(module.initialize_socket_event_handler(MagicMock()))

        assert first is second
        assert module.get_socket_event_handler() is first
        asyncio.run(first._stop_queue_processor())
    finally:
        module.socket_event_handler = original
