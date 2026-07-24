"""RUN ID propagation for CPQ logging.

One run_id is minted per CpqSession (see CpqSession.run_id in state.py) and
set here once per incoming ask request — every "cpq: ..." log line emitted
anywhere in engine.py/bml.py/rdb.py during that request then carries it,
without changing a single existing logger.info(...) call site.

Deliberately a contextvar + logging.Filter, not a function parameter
threaded through every CpqEngine/BmlEvaluator method: those methods are
called directly (with no run_id) from 30+ existing unit tests
(tests/test_cpq_e2e.py) that construct rule/attr objects in isolation —
adding a required parameter would touch every one of them for a
logging-only concern. A contextvar has no such cost: absent (tests, or any
caller that never sets it), the filter silently adds nothing.
"""
from __future__ import annotations

import contextvars
import logging

_run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "cpq_run_id", default="",
)


def set_run_id(run_id: str) -> None:
    """Bind the current run_id for this request/task context."""
    _run_id_var.set(run_id or "")


def get_run_id() -> str:
    return _run_id_var.get()


class RunIdLogFilter(logging.Filter):
    """Appends ``[run_id=...]`` to every log record while a run_id is bound.

    Mutates record.msg directly (rather than only adding a record attribute
    consumed by `%(run_id)s` in a format string) so the id is visible in
    whatever format the hosting application already configured — this
    module doesn't own or control the app's root logging setup.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        run_id = _run_id_var.get()
        if run_id:
            record.msg = f"{record.msg} [run_id={run_id}]"
        return True


def install_run_id_logging(logger_name: str) -> None:
    """Attach the run_id filter to one module's logger (pass ``__name__``
    from the calling module — e.g. engine.py/bml.py/ask_api.py each call
    this once, right after their own ``logging.getLogger(__name__)``).

    A Logger's own `.filters` only apply to records that logger's `.handle`
    processes directly — a Filter attached to a PARENT logger (e.g.
    "aryx.cpq") is NOT consulted for a child logger's own records (e.g.
    "aryx.cpq.engine"), since Python's logging module only walks the
    HANDLER chain upward, not the per-logger filter chain. So this must be
    called once per actual `__name__` logger that emits "cpq: ..." lines,
    not once for a shared namespace prefix.

    Idempotent — safe to call on every import (module-level logger objects
    are singletons; a second call is a no-op, not a duplicate filter).
    """
    target = logging.getLogger(logger_name)
    if not any(isinstance(f, RunIdLogFilter) for f in target.filters):
        target.addFilter(RunIdLogFilter())
