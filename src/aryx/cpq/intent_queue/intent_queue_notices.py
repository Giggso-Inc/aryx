"""User-visible notices for dropped intents and queue overflow.

Split out of `cpq/intent_queue.py` (Raven Style Compliance Plan, Phase
2b, 2026-09-03). Zero test patches against this module — confirmed via
grep.
"""
from __future__ import annotations

from typing import Any

from aryx.cpq.state import INTENT_QUEUE_CAP


def format_dropped_intent_notice(
    dropped_vns: list[str],
    attrs: list[Any] | None = None,
) -> str:
    """User-visible line for dropped intents (never fail the turn silently)."""
    if not dropped_vns:
        return ""
    by_vn = {
        getattr(a, "variable_name", ""): (
            getattr(a, "display_label", "") or getattr(a, "variable_name", "")
        )
        for a in (attrs or [])
    }
    labels = [by_vn.get(v) or v for v in dropped_vns]
    joined = ", ".join(f"**{lbl}**" for lbl in labels)
    return f"⚠️ I couldn't process: {joined} — please re-ask."


def format_queue_overflow_notice(
    overflow_vns: list[str],
    attrs: list[Any] | None = None,
) -> str:
    """User-visible line when intent queue hits the cap."""
    if not overflow_vns:
        return ""
    by_vn = {
        getattr(a, "variable_name", ""): (
            getattr(a, "display_label", "") or getattr(a, "variable_name", "")
        )
        for a in (attrs or [])
    }
    labels = [by_vn.get(v) or v for v in overflow_vns]
    joined = ", ".join(f"**{lbl}**" for lbl in labels)
    return (
        f"⚠️ I can only track {INTENT_QUEUE_CAP} additional change targets at "
        f"once — please re-ask about: {joined}."
    )
