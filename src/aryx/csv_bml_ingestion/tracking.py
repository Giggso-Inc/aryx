"""Raven logging for the pipeline: one tracker per run, one span per step.

Wraps ``aryx.raven_log.raven_log`` so every record carries the run's
``trace_id``, the step's ``span_id`` and a ``context["step"]`` tag. Logging
must never be the reason an ingestion fails, so emit errors are swallowed
and demoted to a stdlib warning.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.csv_bml_ingestion.constants import RAVEN_COMPONENT

logger = logging.getLogger(__name__)


def _raven():  # noqa: ANN202 -- lazy so importing the package never needs raven_logger
    from aryx import raven_log as mod  # noqa: PLC0415
    return mod


class RunTracker:
    """Emits Raven records for a single ingestion run (one CSV file)."""

    def __init__(self, source: str) -> None:
        self.source = source
        try:
            mod = _raven()
            # Inside an ingestion worker the job id is bound (bind_run_id), so
            # these records share the upload's trace_id; the CLI has none.
            self.trace_id: str | None = mod.current_run_id() or mod.new_trace_id()
            self._new_span = mod.new_span_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("csv_bml_ingestion: raven unavailable, using stdlib logging only: %s", exc)
            self.trace_id = None
            self._new_span = lambda: None  # type: ignore[assignment]

    def emit(
        self,
        level: str,
        criticality: str,
        step: str,
        message: str,
        *,
        error_code: str = "",
        **context: Any,
    ) -> None:
        """Emit one Raven record plus the equivalent stdlib log line."""
        ctx = {"component": RAVEN_COMPONENT, "step": step, "source": self.source, **context}
        getattr(logger, {"ERROR": "error", "WARN": "warning", "DEBUG": "debug"}.get(level, "info"))(
            "%s step=%s source=%s %s%s", RAVEN_COMPONENT, step, self.source, message,
            f" [{error_code}]" if error_code else "",
        )
        try:
            _raven().raven_log(
                level=level,  # type: ignore[arg-type]
                criticality=criticality,  # type: ignore[arg-type]
                message=message,
                error_code=error_code,
                trace_id=self.trace_id,
                span_id=self._new_span(),
                context=ctx,
            )
        except Exception as exc:  # noqa: BLE001 -- observability must not break ingestion
            logger.warning("csv_bml_ingestion: raven emit failed step=%s: %s", step, exc)

    def info(self, step: str, message: str, **context: Any) -> None:
        """P4 informational record."""
        self.emit("INFO", "P4", step, message, **context)

    def debug(self, step: str, message: str, **context: Any) -> None:
        """P4 debug record."""
        self.emit("DEBUG", "P4", step, message, **context)

    def warn(self, step: str, message: str, *, error_code: str = "", **context: Any) -> None:
        """P3 warning (policy violation / anomaly)."""
        self.emit("WARN", "P3", step, message, error_code=error_code, **context)

    def error(self, step: str, message: str, *, error_code: str, **context: Any) -> None:
        """P2 error — the run for this file cannot continue."""
        self.emit("ERROR", "P2", step, message, error_code=error_code, **context)
