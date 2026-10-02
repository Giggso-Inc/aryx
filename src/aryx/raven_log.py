"""Aryx wrapper around the raven-logger SDK (raven-log contract).

Every ``raven_log()`` call in this codebase goes through here, never through
``raven_logger`` directly, so env/principal defaults, level filtering, the
sink choice and fail-open behaviour stay in one place.

Behaviour (all controlled by env, read lazily, see ``_load_cfg``):

- ``ARYX_RAVEN_LOG_ENABLED`` (default true): ``false`` makes every call a no-op.
- ``ARYX_RAVEN_LOG_LEVEL`` (default INFO): minimum level written. DEBUG < INFO <
  WARN < ERROR; a record below the level returns before anything else is done.
- ``ARYX_RAVEN_LOG_SINK`` (default stdout): ``stdout``, ``s3`` or ``both``.
- S3 settings: ``ARYX_RAVEN_LOG_S3_PATH`` (``s3://bucket/prefix/``),
  ``..._S3_ACCESS_ID``, ``..._S3_ACCESS_TOKEN``, ``..._S3_REGION`` (no default,
  a missing region is an error), ``..._S3_FLUSH_SECONDS``, ``..._S3_BATCH_MAX``,
  ``..._S3_QUEUE_MAX``.

The wrapper never raises into the app. S3 writes go through a bounded queue and
a daemon thread that uploads JSON-lines batches.

Content rule: ``context`` carries ids, counts, scores, thresholds, flags,
names and timings. Never row data, file content, SQL bind values, prompts,
customer replies or credentials (a defensive scrub redacts the obvious keys).
"""
from __future__ import annotations

import atexit
import contextvars
import hashlib
import json
import logging
import os
import socket
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional

try:  # the OCI Function image does not ship raven-logger
    from raven_logger import new_span_id, new_trace_id, raven_log as _sdk_raven_log

    _SDK = True
except Exception:  # pragma: no cover - exercised via monkeypatch in tests
    _SDK = False
    _sdk_raven_log = None

    def new_trace_id() -> str:
        """Generate a trace id (local fallback when the SDK is missing)."""
        return str(uuid.uuid4())

    def new_span_id() -> str:
        """Generate a span id (local fallback when the SDK is missing)."""
        return str(uuid.uuid4())[:8]


__all__ = [
    "new_span_id", "new_trace_id", "raven_log", "would_log", "bind_run_id",
    "current_run_id", "submit_ctx", "ctx_callable", "value_fields", "flush",
    "reload_config",
]

logger = logging.getLogger(__name__)

SERVICE = "aryx-api"
PROJECT = "aryx"
SCHEMA_VERSION = "1.0"
_DEFAULT_PRINCIPAL = "service:aryx-api"
_VALID_ENVS = frozenset({"prod", "staging", "dev"})
_VALID_LEVELS = frozenset({"ERROR", "WARN", "INFO", "DEBUG"})
_VALID_CRITS = frozenset({"P1", "P2", "P3", "P4"})
_RANK = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
_LEVEL_ALIASES = {"WARNING": "WARN", "CRITICAL": "ERROR", "FATAL": "ERROR"}

# Ingestion workers (job id / discovery id) bind this var with bind_run_id().
# The CPQ ask path binds its own run id in aryx.cpq.logging_context; that module
# is read lazily below rather than imported, because importing aryx.cpq pulls in
# the whole engine (which imports this module).
_run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("raven_run_id", default="")
_CPQ_CTX_MODULE = "aryx.cpq.logging_context"


def bind_run_id(run_id: str) -> None:
    """Bind the id (job id, discovery id) for this context; records use it as trace_id."""
    _run_id_var.set(run_id or "")


def current_run_id() -> str:
    """Return the bound id: ingestion job id, else the CPQ run id ('' when none)."""
    own = _run_id_var.get()
    if own:
        return own
    cpq = sys.modules.get(_CPQ_CTX_MODULE)
    return cpq.get_run_id() if cpq is not None else ""


def ctx_callable(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Return ``fn`` wrapped to run inside a snapshot of the caller's context."""
    ctx = contextvars.copy_context()

    def _run(*args: Any, **kwargs: Any) -> Any:
        return ctx.run(fn, *args, **kwargs)

    return _run


def submit_ctx(executor: Any, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """``executor.submit(fn, ...)`` with the caller's context copied in."""
    return executor.submit(ctx_callable(fn), *args, **kwargs)


_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class _Cfg:
    enabled: bool
    min_rank: int
    sink: str
    s3_path: str
    s3_id: str
    s3_token: str
    s3_region: str
    flush_s: float
    batch_max: int
    queue_max: int


def _env_str(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_num(name: str, default: float, cast: Callable[[Any], Any]) -> Any:
    raw = os.environ.get(name)
    try:
        value = cast(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        _warn_once(f"bad {name}={raw!r}; using {default}")
        value = default
    return value if value > 0 else default


def _load_cfg() -> _Cfg:
    raw_level = _env_str("ARYX_RAVEN_LOG_LEVEL", "INFO").upper()
    level = _LEVEL_ALIASES.get(raw_level, raw_level)
    if level not in _RANK:
        _warn_once(f"bad ARYX_RAVEN_LOG_LEVEL={level!r}; using INFO")
        level = "INFO"
    sink = _env_str("ARYX_RAVEN_LOG_SINK", "stdout").lower()
    if sink not in ("stdout", "s3", "both"):
        _warn_once(f"bad ARYX_RAVEN_LOG_SINK={sink!r}; using stdout")
        sink = "stdout"
    return _Cfg(
        enabled=_env_str("ARYX_RAVEN_LOG_ENABLED", "true").lower() in _TRUE,
        min_rank=_RANK[level],
        sink=sink,
        s3_path=_env_str("ARYX_RAVEN_LOG_S3_PATH"),
        s3_id=_env_str("ARYX_RAVEN_LOG_S3_ACCESS_ID"),
        s3_token=_env_str("ARYX_RAVEN_LOG_S3_ACCESS_TOKEN"),
        s3_region=_env_str("ARYX_RAVEN_LOG_S3_REGION"),
        flush_s=_env_num("ARYX_RAVEN_LOG_S3_FLUSH_SECONDS", 5.0, float),
        batch_max=_env_num("ARYX_RAVEN_LOG_S3_BATCH_MAX", 500, int),
        queue_max=_env_num("ARYX_RAVEN_LOG_S3_QUEUE_MAX", 20000, int),
    )


_lock = threading.Lock()
_CFG: Optional[_Cfg] = None
_SINKS: Optional[list[Callable[[dict], None]]] = None
_warned: dict[str, float] = {}


def _warn_once(msg: str) -> None:
    """Report a wrapper problem on the stdlib logger, once a minute per text."""
    now = time.monotonic()
    if now - _warned.get(msg, -1e9) >= 60:
        _warned[msg] = now
        logger.warning("raven_log: %s", msg)


def _cfg() -> _Cfg:
    global _CFG
    if _CFG is None:
        with _lock:
            if _CFG is None:
                _CFG = _load_cfg()
    return _CFG


def reload_config() -> None:
    """Drop cached config and sinks (tests, or after env changes at runtime)."""
    global _CFG, _SINKS
    with _lock:
        sinks = _SINKS
        _CFG = None
        _SINKS = None
    for sink in sinks or []:
        close = getattr(sink, "close", None)
        if close:
            close()


def _dumps(record: dict) -> str:
    return json.dumps(record, default=str)


def _stdout_sink(record: dict) -> None:
    print(_dumps(record), flush=True)


class _S3BatchEmitter:
    """Queue records and upload them to S3 as JSON-lines batches off-thread.

    When the bounded queue is full the lowest level is evicted first (DEBUG,
    then INFO, then WARN); the incoming record is dropped instead if it is not
    more important than everything queued. Drops are counted and written as one
    WARN record with the next batch.
    """

    _ORDER = ("DEBUG", "INFO", "WARN", "ERROR")

    def __init__(self, cfg: _Cfg, client: Any = None) -> None:
        if not cfg.s3_path.startswith("s3://"):
            raise ValueError("ARYX_RAVEN_LOG_S3_PATH must start with s3://")
        for name, val in (("ACCESS_ID", cfg.s3_id), ("ACCESS_TOKEN", cfg.s3_token),
                          ("REGION", cfg.s3_region)):
            if not val:
                raise ValueError(f"ARYX_RAVEN_LOG_S3_{name} is required for sink s3/both")
        bucket, _, prefix = cfg.s3_path[5:].partition("/")
        if not bucket:
            raise ValueError("ARYX_RAVEN_LOG_S3_PATH has no bucket")
        self._bucket = bucket
        self._prefix = (prefix.rstrip("/") + "/") if prefix.strip("/") else ""
        self._client = client if client is not None else _make_s3_client(cfg)
        self._flush_s = cfg.flush_s
        self._batch_max = cfg.batch_max
        self._max = cfg.queue_max
        self._host = socket.gethostname()
        self._q: dict[str, deque] = {lv: deque() for lv in self._ORDER}
        self._n = 0
        self._dropped = {lv: 0 for lv in self._ORDER}
        self._seq = 0
        self._stop = False
        self._cv = threading.Condition()
        self._thread = threading.Thread(target=self._run, name="raven-log-s3", daemon=True)
        self._thread.start()

    def __call__(self, record: dict) -> None:
        level = record.get("level", "INFO")
        if level not in self._q:
            level = "INFO"
        with self._cv:
            if self._n >= self._max:
                victim = next(lv for lv in self._ORDER if self._q[lv])
                if _RANK[level] <= _RANK[victim]:
                    self._dropped[level] += 1
                    return
                self._q[victim].popleft()
                self._n -= 1
                self._dropped[victim] += 1
            self._q[level].append(record)
            self._n += 1
            if self._n >= self._batch_max:
                self._cv.notify()

    def _take(self) -> tuple[list[dict], dict[str, int]]:
        """Pop up to batch_max records (most important first). Caller holds the lock."""
        batch: list[dict] = []
        for lv in reversed(self._ORDER):
            q = self._q[lv]
            while q and len(batch) < self._batch_max:
                batch.append(q.popleft())
        self._n -= len(batch)
        dropped = {lv: c for lv, c in self._dropped.items() if c}
        for lv in dropped:
            self._dropped[lv] = 0
        return batch, dropped

    def _run(self) -> None:
        while True:
            with self._cv:
                if not self._stop and self._n < self._batch_max:
                    self._cv.wait(timeout=self._flush_s)
                batch, dropped = self._take()
                done = self._stop and self._n == 0
            self._write(batch, dropped)
            if done:
                return

    def _write(self, batch: list[dict], dropped: dict[str, int]) -> None:
        if dropped:
            batch.append(_build_local("WARN", "P3", "raven-log queue overflow dropped records",
                                      error_code="ARYX_RAVEN_LOG_DROPPED",
                                      context={"dropped_by_level": dropped,
                                               "queue_max": self._max}))
        if not batch:
            return
        batch.sort(key=lambda r: r.get("timestamp", ""))
        now = datetime.now(timezone.utc)
        with self._cv:
            self._seq += 1
            seq = self._seq
        key = (f"{self._prefix}{now:%Y/%m/%d}/{SERVICE}-{self._host}-"
               f"{now:%Y%m%dT%H%M%S}-{seq}.jsonl")
        body = "\n".join(_dumps(r) for r in batch).encode("utf-8")
        _put_object(self._client, self._bucket, key, body, len(batch))

    def flush(self) -> None:
        """Upload everything queued, in the calling thread."""
        while True:
            with self._cv:
                batch, dropped = self._take()
            if not batch and not dropped:
                return
            self._write(batch, dropped)

    def close(self) -> None:
        """Stop the worker and upload what is left."""
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        self._thread.join(timeout=10)
        self.flush()


def _make_s3_client(cfg: _Cfg) -> Any:
    import boto3  # ImportError is caught by the sink factory

    return boto3.client("s3", aws_access_key_id=cfg.s3_id,
                        aws_secret_access_key=cfg.s3_token, region_name=cfg.s3_region)


def _put_object(client: Any, bucket: str, key: str, body: bytes, count: int) -> None:
    try:
        client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/x-ndjson")
    except Exception as exc:
        _warn_once(f"S3 upload failed, {count} record(s) lost: {exc!r}")


def _get_sinks() -> list[Callable[[dict], None]]:
    global _SINKS
    if _SINKS is not None:
        return _SINKS
    with _lock:
        if _SINKS is not None:
            return _SINKS
        cfg = _cfg()
        sinks: list[Callable[[dict], None]] = []
        if cfg.sink in ("stdout", "both"):
            sinks.append(_stdout_sink)
        if cfg.sink in ("s3", "both"):
            s3 = _try_s3(cfg)
            sinks.append(s3 if s3 is not None else _stdout_sink)
            if s3 is not None:
                atexit.register(flush)
        _SINKS = list(dict.fromkeys(sinks))
        return _SINKS


def _try_s3(cfg: _Cfg) -> Optional[_S3BatchEmitter]:
    try:
        return _S3BatchEmitter(cfg)
    except Exception as exc:
        _warn_once(f"S3 sink unavailable ({exc!r}); falling back to stdout")
        return None


def flush() -> None:
    """Upload anything the S3 sink still holds (also runs at interpreter exit)."""
    for sink in list(_SINKS or []):
        fn = getattr(sink, "flush", None)
        if fn:
            fn()


def _emit(record: dict) -> None:
    for sink in _get_sinks():
        _safe_sink(sink, record)


def _safe_sink(sink: Callable[[dict], None], record: dict) -> None:
    try:
        sink(record)
    except Exception as exc:
        _warn_once(f"sink {type(sink).__name__} failed: {exc!r}")


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


def _build_local(level: str, criticality: str, message: str, *, error_code: str = "",
                 service: str = SERVICE, env: Optional[str] = None,
                 principal: str = _DEFAULT_PRINCIPAL, project: str = PROJECT,
                 trace_id: Optional[str] = None, span_id: Optional[str] = None,
                 context: Optional[dict] = None, sample_payload: str = "") -> dict:
    """Build a record in the raven-log shape (used when the SDK is missing)."""
    if level not in _VALID_LEVELS:
        raise ValueError(f"level {level!r} invalid")
    if criticality not in _VALID_CRITS:
        raise ValueError(f"criticality {criticality!r} invalid")
    if level in ("ERROR", "WARN") and not error_code:
        raise ValueError(f"error_code is required when level is {level}")
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level, "criticality": criticality, "service": service,
        "env": env or _env(), "trace_id": trace_id or current_run_id() or new_trace_id(),
        "span_id": span_id or new_span_id(), "principal": principal,
        "error_code": error_code, "message": message, "context": context or {},
        "sample_payload": sample_payload, "project": project,
    }


_FORBIDDEN_KEYS = frozenset({
    "params", "row0", "bind", "binds", "sql_params", "password", "passwd", "secret",
    "token", "access_token", "api_key", "apikey", "authorization", "headers",
    "prompt", "reply", "user_message", "answer_text", "content", "content_b64",
    "file_content", "body", "payload", "text",
})


def _scrub(obj: Any, depth: int = 0) -> Any:
    """Redact forbidden keys (content rule). Copies only when something is hit."""
    if depth > 3 or not isinstance(obj, dict):
        return obj
    out = None
    for key, val in obj.items():
        if isinstance(key, str) and key.lower() in _FORBIDDEN_KEYS:
            new: Any = "[redacted]"
        else:
            new = _scrub(val, depth + 1)
        if new is not val:
            if out is None:
                out = dict(obj)
            out[key] = new
    return obj if out is None else out


def value_fields(value: Any, *, free_text: bool = False) -> dict[str, Any]:
    """Fields describing an attribute value for a record's ``context`` (D6).

    Enumerated and numeric values are logged as they are (catalog data). Free
    text, and anything the customer typed, is logged as length + short hash.
    """
    if value is None:
        return {"value_kind": "none"}
    if free_text:
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        return {"value_kind": "free_text", "value_len": len(text),
                "value_hash": hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]}
    if isinstance(value, (list, tuple, set, frozenset)):
        return {"value_kind": "enumerated_multi", "value": sorted(str(v) for v in value)}
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    return {"value_kind": "numeric" if numeric else "enumerated", "value": value}


def would_log(level: str) -> bool:
    """True if a record at ``level`` would be written (lets callers skip building context)."""
    cfg = _cfg()
    lv = _LEVEL_ALIASES.get(str(level).upper(), str(level).upper())
    return cfg.enabled and _RANK.get(lv, 100) >= cfg.min_rank


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
    """Emit one raven-log record with Aryx defaults; never raises.

    Returns the record, or ``{}`` when it was filtered out, disabled or failed.
    ``trace_id`` defaults to the id bound with ``bind_run_id`` (job id / CPQ run
    id), else a fresh one.
    """
    lv = _LEVEL_ALIASES.get(str(level).upper(), str(level).upper())
    cfg = _cfg()
    if not cfg.enabled or _RANK.get(lv, 100) < cfg.min_rank:
        return {}
    kwargs: dict[str, Any] = dict(
        error_code=error_code, service=service, env=env or _env(),
        principal=principal, project=project,
        trace_id=trace_id or current_run_id() or None, span_id=span_id,
        context=_scrub(context) if context else context, sample_payload=sample_payload,
    )
    return _emit_record(lv, criticality, message, kwargs)


def _emit_record(lv: str, criticality: str, message: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        if _SDK:
            return _sdk_raven_log(level=lv, criticality=criticality, message=message,
                                  _emit=_emit, **kwargs)
        record = _build_local(lv, criticality, message, **kwargs)
        _emit(record)
        return record
    except Exception as exc:
        _warn_once(f"call failed ({type(exc).__name__}: {exc})")
        return {}
