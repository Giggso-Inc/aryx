"""Aryx wrapper around the raven-logger SDK (raven-log contract).

Default service/project tags for this codebase. Prefer importing from here
rather than calling ``raven_logger`` directly so env/principal defaults stay
consistent.

Example::

    from aryx.raven_log import raven_log, new_trace_id, new_span_id

    raven_log(
        level="INFO",
        criticality="P4",
        message="health check ok",
        error_code="",
    )
"""
from __future__ import annotations

import os
from typing import Any, Literal, Optional

from raven_logger import new_span_id, new_trace_id, raven_log as _raven_log

__all__ = ["new_span_id", "new_trace_id", "raven_log"]

SERVICE = "aryx-api"
PROJECT = "aryx"
_DEFAULT_PRINCIPAL = "service:aryx-api"
_VALID_ENVS = frozenset({"prod", "staging", "dev"})


def _env() -> Literal["prod", "staging", "dev"]:
    """Map ARYX_ENV (or ENV) into the raven-log env enum."""
    raw = (os.environ.get("ARYX_ENV") or os.environ.get("ENV") or "dev").lower()
    if raw in ("production", "prd"):
        raw = "prod"
    if raw in ("stage", "stg"):
        raw = "staging"
    if raw in ("development", "local", "test"):
        raw = "dev"
    return raw if raw in _VALID_ENVS else "dev"  # type: ignore[return-value]


def raven_log(
    level: Literal["ERROR", "WARN", "INFO", "DEBUG"],
    criticality: Literal["P1", "P2", "P3", "P4"],
    message: str,
    *,
    error_code: str = "",
    service: str = SERVICE,
    env: Optional[Literal["prod", "staging", "dev"]] = None,
    principal: str = _DEFAULT_PRINCIPAL,
    project: str = PROJECT,
    trace_id: Optional[str] = None,
    span_id: Optional[str] = None,
    context: Optional[dict[str, Any]] = None,
    sample_payload: str = "",
) -> dict[str, Any]:
    """Emit one raven-log record with Aryx defaults filled in."""
    return _raven_log(
        level=level,
        criticality=criticality,
        message=message,
        service=service,
        env=env or _env(),
        principal=principal,
        project=project,
        error_code=error_code,
        trace_id=trace_id,
        span_id=span_id,
        context=context,
        sample_payload=sample_payload,
    )
