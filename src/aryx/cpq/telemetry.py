"""Divergence telemetry for LLM-first vs deterministic intent.

Logs per run_id: LLM intent, deterministic intent, agreement flag,
model_id, rejected outputs. Emits a warning catch when the rolling
disagreement rate exceeds 20%.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

DISAGREE_RATE_WARN = 0.20
_WINDOW = 50
_lock = threading.Lock()
_recent: deque[bool] = deque(maxlen=_WINDOW)  # True = agreed


@dataclass
class DivergenceRecord:
    run_id: str
    llm_intent: str | None
    deterministic_intent: str | None
    agreement: bool
    model_id: str
    variable_name: str | None = None
    rejected: list[str] = field(default_factory=list)
    reason: str = ""


def log_divergence(record: DivergenceRecord) -> str | None:
    """Log one turn's divergence data. Returns warning catch message or None."""
    with _lock:
        _recent.append(record.agreement)
        total = len(_recent)
        agreed = sum(1 for a in _recent if a)
        rate = 1.0 - (agreed / total) if total else 0.0

    logger.info(
        "cpq_divergence: run_id=%s llm=%s det=%s agree=%s model=%s vn=%r "
        "rejected=%s reason=%r window_disagree_rate=%.2f (n=%d)",
        record.run_id,
        record.llm_intent,
        record.deterministic_intent,
        record.agreement,
        record.model_id,
        record.variable_name,
        record.rejected[:5],
        record.reason,
        rate,
        total,
    )

    if total >= 10 and rate > DISAGREE_RATE_WARN:
        msg = (
            f"⚠️ Intent divergence is elevated "
            f"({rate:.0%} disagreement over last {total} turns). "
            "Consider **guided** mode for safer, step-by-step configuration."
        )
        logger.warning(
            "cpq_divergence: RATE WARNING run_id=%s rate=%.2f",
            record.run_id, rate,
        )
        return msg
    return None


def log_rejection(
    run_id: str,
    model_id: str,
    invalid_values: list[str],
    context: str = "",
) -> None:
    logger.info(
        "cpq_divergence: rejected_output run_id=%s model=%s values=%s ctx=%s",
        run_id, model_id, invalid_values[:10], context,
    )


def disagreement_rate() -> float:
    with _lock:
        if not _recent:
            return 0.0
        return 1.0 - (sum(1 for a in _recent if a) / len(_recent))


def reset_telemetry() -> None:
    """Test helper."""
    with _lock:
        _recent.clear()


def deterministic_category_summary(signals: dict[str, set[str]]) -> str | None:
    """Pick a primary deterministic category label from probe signals."""
    for cat, vns in signals.items():
        if vns:
            return cat
    return None
